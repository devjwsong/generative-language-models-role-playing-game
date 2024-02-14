from kani import Kani
from kani.models import ChatMessage
from kani.engines.openai import OpenAIEngine
from agents.manager import GameManager
from agents.evaluator import Evaluator
from utils import convert_into_class_idx, print_question_start, print_system_log, select_options
from constants import ASSISTANT_INSTRUCTION, GAMEPLAY_EVALUATOR_INSTRUCTION, SCENE_INIT_EVALUATOR_INSTRUCTION, RULES_EVALUATOR_INSTRUCTION
from utils import log_break, get_player_input
from sentence_transformers import SentenceTransformer
from argparse import Namespace
from datetime import datetime
from pytz import timezone

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
    parser.add_argument('--rule_injection', type=str, default=None, help="The rule injection policy.")

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
        assert args.rule_injection in [None, 'full', 'retrieval'], "Either specify an available rule injection option: 'full' / 'retrieval', or leave it as None."

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
        pass
    
    if args.eval_task == 'scene_init':
        evaluate_scene_init(args, engine)

    if args.eval_task == 'rules':
        evaluate_rules(args, target_model, engine)
