from kani import Kani
from kani.models import ChatMessage
from kani.engines.openai import OpenAIEngine
from agents.manager import GameManager
from agents.evaluator import Evaluator
from utils import convert_into_class_idx, print_question_start, print_system_log, convert_into_message
from constants import (
    ASSISTANT_INSTRUCTION, 
    HISTORY_CONSISTENCY_EVALUATOR_INSTRUCTION,
    STATE_CONSISTENCY_EVALUATOR_INSTRUCTION,
    RULE_CONSISTENCY_EVALUATOR_INSTRUCTION,
    INTEREST_EVALUATOR_INSTRUCTION,
    SCENE_INIT_EVALUATOR_INSTRUCTION, 
    RULES_EVALUATOR_INSTRUCTION,
)
from utils import log_break, get_player_input
from sentence_transformers import SentenceTransformer
from argparse import Namespace
from datetime import datetime
from pytz import timezone
from tqdm import tqdm

import asyncio
import argparse
import json
import logging
import torch
import numpy as np
import random
import os

log = logging.getLogger("kani")
message_log = logging.getLogger("kani.messages")


# Exporting the evaluation scores.
def export_test_result(data: dict, path: str):
    directory = '/'.join(path.split('/')[:-1])

    # Setting the directory.
    if not os.path.isdir(directory):
        os.makedirs(directory)

    with open(path, 'w') as f:
        json.dump(data, f)


# Sublogic for history consistency evaluation.
async def evaluate_history_consistency(engine: OpenAIEngine, past_history: list[dict], current_queries: list[dict], generated: dict):
    options = [
        "It is perfectly relevant to the whole previous interactions.",
        "It is only relevant to the immediate input queries.",
        "It totally makes no sense.",
    ]
    options_str = '\n'.join([f"{o}: {option}" for o, option in enumerate(options)])

    # Setting the evalutor.
    system_prompt = ' '.join(HISTORY_CONSISTENCY_EVALUATOR_INSTRUCTION)
    evaluator = Evaluator(
        engine=engine, 
        system_prompt=system_prompt,
        chat_history=[convert_into_message(hist) for hist in past_history] + [convert_into_message(query) for query in current_queries]
    )

    res = await evaluator.chat_round_str(f"Is the generated response from Goblin King relevant to the dialogue so far?\nResponse: {generated['content']}\n\n{options_str}")
    res = convert_into_class_idx(res, options)

    if res == 0:
        score = 1.0
    elif res == 1:
        score = 0.5
    else:
        score = 0.0

    return {'history_consistency': {options[res]: score}}


# Sublogic for state consistency evaluation.
async def evaluate_state_consistency(engine: OpenAIEngine, scene: dict, players: list, generated: dict):
    options = [
        "Perfectly consistent with the current scene and the status of players.",
        "Partially consistent with the current game state. (e.g. Consistent with only either the scene or the players.)",
        "Completely inconsistent."
    ]
    options_str = '\n'.join([f"{o}: {option}" for o, option in enumerate(options)])

    # Setting the evaluator.
    content = f"chapter={scene['chapter']}, scene={scene['scene']}, scene_summary={scene['scene_summary']}, " + \
        f"npcs={scene['npcs']}, generation_rules={scene['generation_rules']}, success_condition={scene['success_condition']}, failure_condition={scene['failure_condition']}, " + \
        f"game_flow={scene['game_flow']}, environement={scene['environment']}, random_tables={scene['random_tables']}, consequences={scene['consequences']}, " + \
        f"is_action_scene={scene['is_action_scene']}"
    scene_prompt = ChatMessage.system(name="Scene_State", content=content)

    player_prompts = []
    for player in players:
        content = f"name={player['name']}, kin={player['kin']}, persona={player['persona']}, goal={player['goal']}, " + \
            f"traits={player['traits']}, flaws={player['flaws']}, inventory={player['inventory']}, additional_notes={player['additional_notes']}"
        player_prompt = ChatMessage.system(name="Player_State", content=content)
        player_prompts.append(player_prompt)
    
    
    system_prompt = ' '.join(STATE_CONSISTENCY_EVALUATOR_INSTRUCTION)
    evaluator = Evaluator(
        engine=engine, 
        system_prompt=system_prompt,
        chat_history=[scene_prompt] + player_prompts
    )

    res = await evaluator.chat_round_str(f"Is the generated response from Goblin King consistent with the current scene and players' status?\nResponse: {generated['content']}\n\n{options_str}")
    res = convert_into_class_idx(res, options)

    if res == 0:
        score = 1.0
    elif res == 1:
        score = 0.5
    else:
        score = 0.0

    return {'state_consistency': {options[res]: score}}


# Sublogic for rule consistency evaluation.
async def evaluate_rule_consistency(engine: OpenAIEngine, generated: dict):
    options = [
        "Perfectly consistent with the game rule."
        "Violating the game rule."
    ]
    options_str = '\n'.join([f"{o}: {option}" for o, option in enumerate(options)])

    system_prompt = ' '.join(RULE_CONSISTENCY_EVALUATOR_INSTRUCTION)
    evaluator = Evaluator(
        engine=engine, 
        system_prompt=system_prompt
    )

    res = await evaluator.chat_round_str(f"Is the generated response from Goblin King consistent with the game rules?\nResponse: {generated['content']}\n\n{options_str}")
    res = convert_into_class_idx(res, options)

    if res == 0:
        score = 1.0
    elif res == 1:
        score = 0.0

    return {'rule_consistency': {options[res]: score}}


# Sublogic for interest evaluation.
async def evaluate_interest(engine: OpenAIEngine, generated: dict):
    options = [
        "Interesting and entertaining!",
        "Boring and bland..."
    ]
    options_str = '\n'.join([f"{o}: {option}" for o, option in enumerate(options)])

    system_prompt = ' '.join(INTEREST_EVALUATOR_INSTRUCTION)
    evaluator = Evaluator(
        engine=engine, 
        system_prompt=system_prompt
    )

    res = await evaluator.chat_round_str(f"Is the generated response from Goblin King interesting?\nResponse: {generated['content']}\n\n{options_str}")
    res = convert_into_class_idx(res, options)

    if res == 0:
        score = 1.0
    elif res == 1:
        score = 0.0

    return {'interest': {options[res]: score}}


# Evaluating the holistic quality of the gameplay.
def evaluate_gameplay(args: Namespace, engine: OpenAIEngine):
    # Loading the gameplay data.
    with open(args.gameplay_path, 'r') as f:
        game = json.load(f)

    async def test():
        result = {}
        turn_scores = []

        for t, turn in enumerate(tqdm(game)):
            scene_state = turn['scene']
            player_states = turn['players']
            past_history = turn['past_history']
            current_queries = turn['current_queries']
            generated = turn['generated']

            turn_score = {}

            # Response generation.
            if generated['role'] == 'assistant':
                # 1. History consistency.
                res = await evaluate_history_consistency(engine, past_history, current_queries, generated)
                turn_score.update(res)

                # 2. State consistency.
                res = await evaluate_state_consistency(engine, scene_state, player_states, generated)
                turn_score.update(res)

                # 3. Rule consistency.
                res = await evaluate_rule_consistency(engine, generated)
                turn_score.update(res)

                # 4. Interest.
                res = await evaluate_interest(engine, generated)
                turn_score.update(res)

            turn_scores.append(turn_score)

        result['per_turn'] = turn_scores

        export_test_result(result, f"evaluations/{args.gameplay_path}")

    asyncio.run(test())


# Evaluating the scene quality. Note that this function only evaluate the quality of the generation. (0.8 or 1.0)
def evaluate_scene_init(args: Namespace, engine: OpenAIEngine):
    # Loading the initialized scene and original scene input.
    with open(args.scene_path, 'r') as f:
        output = json.load(f)
    scene_idx = int(args.scene_path.split('/')[1].replace('scene=', ''))
    with open("data/scenes.json", 'r') as f:
        original = json.load(f)[scene_idx]

    # Setting the evaluator model.
    system_prompt = ' '.join(SCENE_INIT_EVALUATOR_INSTRUCTION)
    evaluator = Evaluator(engine=engine, system_prompt=system_prompt)

    async def test():
        options = [
            "In terms of the content, it is perfectly matched with the original input.",
            "The generated output is somewhat unnatural or contradictory."    
        ]
        options_str = '\n'.join([f"{o}: {option}" for o, option in enumerate(options)])
        res = await evaluator.chat_round_str(f"Comparing the original scene and the generated output, which option is closer to your decision?\nOriginal: {original}\nOutput: {output}\n\n{options_str}")
        res = convert_into_class_idx(res, options)

        if res == 0:  # 1.0: Perfect.
            score = 1.0
            print_system_log("THE RESULT OF SCENE INITIALIZATION EVALUATION: 1.0")
        else:  # 0.8: Suboptimal.
            score = 0.8
            print_system_log("THE RESULT OF SCENE INITIALIZATION EVALUATION: 0.8")

        result = {
            'scene_quality': {options[res]: score}
        }
        export_test_result(result, f"evaluations/{args.scene_path}")

    asyncio.run(test())


# Evaluating the rule understanding capability of a model.
def evaluate_rules(args: Namespace, target_model: Kani, engine: OpenAIEngine):
    # The list of test questions.
    questions = [
        'What is the difference between a test and an action scene?',
        'List all properties that one player character can have during the game.',
        'What is required for evaluating if the NPC says or behaves properly during the game?',
        'Assume that the difficulty of a test is 5. If two more players are going to help the test with their traits, what is the final difficulty value?',
        'If the inventory of a player is full and there is an item the player wants to have. What should the player do?',
        'What is this action scene initiated by a player different from the one by the Goblin King?',
        "How long does an NPC stay in the player's party after it joins? Give the specific time amount.",
        'Which amount of the overall time limit in the Labyrinth is?',
        'Describe how the game manager can end the current scene.',
        'How does an action is terminated?',
        'What is the condition that the player can pass the test if the difficulty value is 3?',
        'What is the valid range of difficulty number?',
        'How does the Goblin King use the random tables during the game?',
        'What is the maximum number of items that one player can hold?',
        'If other players decide to help the one who is going to do a test, describe how the test changes depending on the traits or flaws.',
        'What is the effect of the items in the Labyrinth?',
        'What happens if the Goblin King does not notify the decrease of remaining time at every minute?',
        'Assume that the difficulty of a test is 4. If three more players are going to help the test with their traits, what is the final difficulty value?',
        'How many actions are allowed per player at each turn?',
        'How much is the time limit for each player turn during an action scene?',
        'What should the Goblin King do if a player tries to speak with an NPC?',
        'If the result from a dice is 1, what is the possible difficulty range of a test the player can win?',
        "How can we make an NPC stay in the player's group after the Goblin King appears in the scene?",
        'What is the role of the Goblin King during an action scene?',
        'If a player wants to talk with an NPC whose attributes have not been generated by the Goblin King before, what should the Goblin King do?',
        'What is the difficulty of a test for checking if an NPC leaves the party?'
    ]
    random.seed(args.seed)
    random.shuffle(questions)

    questions = questions[:5]

    # Setting the evaluator model with the full rule injection.
    system_prompt = ' '.join(RULES_EVALUATOR_INSTRUCTION)
    evaluator = Evaluator(engine=engine, system_prompt=system_prompt)

    async def test():
        result = {}
        scores = []

        options = [
            "Perfectly correct.",
            "Partially correct. (e.g. dropping essential information, faking up the false rules...)",
            "Completely wrong."
        ]
        options_str = '\n'.join([f"{o}: {option}" for o, option in enumerate(options)])

        for q, question in enumerate(questions):
            query = f"Answer the following question according to the Labyrinth's rules.\n{question}"
            answer = await target_model.chat_round_str(query)
            print_question_start()
            print(f"QUESTION {q+1}: {question}")
            print(f"ANSWER: {answer}")
            log_break()

            # Evaluating the answer.
            res = await evaluator.chat_round_str(f"What do you think about the answer? Select an option which represents your thought the most.\nQuestion: {question}\nAnswer: {answer}\n\n{options_str}")
            res = convert_into_class_idx(res, options)

            if res == 0:
                score = 1.0
            elif res == 1:
                score = 0.5
            else:
                score = 0.0

            scores.append({options[res]: score})

            # Clearing the chat histories for fair evaluations.
            target_model.chat_history.clear()
            evaluator.chat_history.clear()

        assert len(scores) == len(questions), "There is a mismatch between the number of recorded scores and the number of questions."

        result['scores'] = scores
        print_system_log("THE RESULT OF RULE UNDERSTANDING EVALUATION:")
        for s, score in enumerate(scores):
            print(f"{s+1}. Q: {questions[s]}\n => Score: {score}")

        result['total'] = np.sum([v for score in scores for _, v in score.items()])
        result['average'] = np.mean([v for score in scores for _, v in score.items()])
        print_system_log(f"TOTAL: {result['total']}")
        print_system_log(f"AVERAGE: {result['average']}")

        print_question_start()
        print_system_log("THE USERNAME IS REQUIRED TO EXPORT THE TEST RESULT.")
        username = get_player_input(after_break=True)

        now = datetime.now(timezone('US/Eastern'))
        test_time = now.strftime("%Y-%m-%d-%H-%M-%S")
        export_test_result(result, f"evaluations/rules/rule={args.rule_injection}/{username}-model={args.target_model_idx}-seed={args.seed}-time={test_time}.json")

    asyncio.run(test())


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--eval_task', type=str, required=True, help="The name of the evaluation task.")
    parser.add_argument('--eval_model_idx', type=str, required=True, help="The name of the model which is used for the automatic evaluation.")

    # Arguments for the gameplay evalaution.
    parser.add_argument('--gameplay_path', type=str, help="The path of the file which has the whole game play data.")

    # Arguments for the scene intialization evaluation.
    parser.add_argument('--scene_path', type=str, help="The path of the file which has the initialized scene information.")

    # Arguments for the rule understanding evaluation.
    parser.add_argument('--seed', type=int, default=0, help="The random seed for shuffling the question list.")
    parser.add_argument('--target_model_idx', type=str, help="The index of the model which should be evaluated.")
    parser.add_argument('--rule_injection', type=str, default='full', help="The rule injection policy.")
    parser.add_argument('--include_rules', action='store_true', help="Setting whether to include the game rules in the prompt.")

    args = parser.parse_args()

    assert args.eval_task in ['gameplay', 'scene_init', 'rules'], "Specify the correct evaluation task name."

    # Setting the engine for automated evaluation or evaluation of rule understanding.
    api_key = input("Enter the API key for OpenAI API: ")
    log_break()
    engine = OpenAIEngine(api_key, model=args.eval_model_idx)

    # Setting & Validting the arguments for each evaluation task.
    if args.eval_task == 'gameplay':
        assert args.gameplay_path is not None, "You should specify the gameplay data you want to evaluate."
    if args.eval_task == 'scene_init':
        assert args.scene_path is not None, "You should specify the initialized scene data you want to evaluate."
    if args.eval_task == 'rules':
        assert args.target_model_idx is not None, "You should specify the model you want to test."
        assert args.rule_injection in ['full', 'retrieval'], "Specify an available rule injection option: 'full' / 'retrieval'"

        # Setting the sentence encoder for the rule embedding.
        encoder = None
        if args.rule_injection == 'retrieval':
            print("Setting a sentence encoder for retrieval...")
            device = torch.device('cuda:0') if torch.cuda.is_available() else torch.device('cpu')
            encoder = SentenceTransformer('all-mpnet-base-v2').to(device)

        args.concat_policy = 'simple'
        args.max_num_msgs = None
        args.summarization = False
        args.summ_period = None
        args.clear_raw_logs = False
        args.automated_player = False

        # Initializing the target game manager.
        system_prompt = ' '.join(ASSISTANT_INSTRUCTION)
        target_engine = OpenAIEngine(api_key, model=args.target_model_idx)
        target_model = GameManager(
            main_args=args,
            encoder=encoder,
            engine=target_engine, 
            system_prompt=system_prompt
        )

    # Evaluation logics.
    if args.eval_task == 'gameplay':
        evaluate_gameplay(args, engine)
    
    if args.eval_task == 'scene_init':
        evaluate_scene_init(args, engine)

    if args.eval_task == 'rules':
        evaluate_rules(args, target_model, engine)
