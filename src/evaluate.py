from agents.manager import GameManager
from models.kani_models import generate_engine
from utils import select_options
from constant_prompts import INSTRUCTION, RULE_SUMMARY, INIT_QUERY
from typing import Dict

import asyncio
import argparse
import json
import logging

log = logging.getLogger("kani")
message_log = logging.getLogger("kani.messages")


# Checking the types of attributes for initialization.
def check_init_types(manager: GameManager):
    # The scene summary.
    try:
        assert isinstance(manager.scene_summary, list), "The scene summary is not the list type."
        assert len(manager.scene_summary) > 0, "The scene summary must not be empty."

        # The NPCs.
        assert isinstance(manager.npcs, dict), "The npcs attribute is not the dict type."
        if len(manager.npcs) > 0:
            for name, info in manager.npcs.items():
                assert isinstance(name, str), "The name of an NPC is not the string type."
                assert isinstance(info, dict), "The NPC information is not the dict type."
                assert isinstance(info['kin'], str), "The kin of an NPC is not the string type."
                assert isinstance(info['persona'], list), "The persona of an NPC is not the list type."
                assert isinstance(info['goal'], str), "The goal of an NPC is not the string type."
                assert isinstance(info['trait'], str), "The traits of an NPC is not the string type."
                assert isinstance(info['flaw'], str), "The flaws of an NPC is not the string type."

        # The generation rules.
        assert isinstance(manager.generation_rules, list), "The list of generation rules is not the list type."

        # The success condition.
        assert isinstance(manager.success_condition, str), "The success condition is not the string type."
        assert len(manager.success_condition) > 0, "The success condition must not be empty."

        # The failure condition.
        assert isinstance(manager.failure_condition, str), "The failure condition is not the string type."

        # The game flow rules.
        assert isinstance(manager.game_flow, list), "The list of game flow rules is not the list type."

        # The environment.
        assert isinstance(manager.environment, list), "The list of environment specifications is not the list type."
    except AssertionError as e:
        log.error(f"{e}: Assertion error.")
        raise Exception()


def evaluate_init(manager: GameManager, scene: Dict):
    # Converting the query into string.
    init_query = '\n'.join([' '. join(query) for query in INIT_QUERY])

    async def test():
        try:
            await manager.init_scene(
                init_query,
                scene,
            )
            check_init_types(manager)
        except json.decoder.JSONDecodeError:
            return 0.0
        except KeyError:
            return 0.2
        except AssertionError:
            return 0.5
        else:
            # TODO: How to export the export results?
            print()
            manager.show_scene()
            options = [
                {'score': 1.0, 'description': "Perfect contents."},
                {'score': 0.8, 'description': "Suboptimal contents."}
            ]
            selected = select_options(options)
            return selected['score']
    asyncio.run(test())


def evaluate_rules(manager: GameManager):
    # The list of test questions.
    questions = [
        'What is the difference between a test and an action scene?',
        'List all properties that one player character can have during the game.',
        'What is required for evaluating if the NPC says or behaves properly during the game?',
        'Assume that the difficulty of a test is 5. If two more players are going to help the test with their traits, what is the final difficulty value?',
        'If the inventory of a player is full and there is a item the player wants to have. What should the player do?',
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
        "How can we make the NPCs to stay in the player's group after the Goblin King appears in the scene?",
        'What is the role of the Goblin King during an action scene?',
        'If a player wants to talk with an NPC whose attributes have not been generated by the Goblin King before, what should the Goblin King do?',
        'What is the difficulty of a test for checking if an NPC leaves the party?'
    ]

    # The list of the user scores.
    options = [
        {'score': 1.0, 'description': "Perfectly correct."},
        {'score': 0.5, 'description': "Partially correct. (e.g. dropping essential information, faking up the false rules...)"},
        {'score': 0.0, 'description': "Completely wrong."}
    ]
    scores = []

    async def test():
        for q, question in enumerate(questions):
            query = f"Answer the following question according to the Labyrinth's rules.\n{question}"
            response = await manager.chat_round_str(query)
            print()
            print(f"QUESTION {q+1}: {question}")
            print(f"ANSWER: {response}")

            # Recording the user score.
            print("Select the score for the given response.")
            selected = select_options(options)
            scores.append(selected['score'])

            # Clearing the chat history.
            manager.chat_history = []
    asyncio.run(test())

    # TODO: How to export the export results?
    return scores


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--eval_name', type=str, required=True, help="The evaluation name.")
    parser.add_argument('--engine_name', type=str, required=True, help="The engine corresponding the model tested.")
    parser.add_argument('--model_idx', type=str, required=True, help="The model index.")
    parser.add_argument('--rule_injection', type=str, required=False, help="The rule injection type.")
    parser.add_argument('--scene_idx', type=int, help="The index of the scene for the initialization evaluation.")

    args = parser.parse_args()

    assert args.eval_name in ['init', 'rules'], "Specify the correct evaluation name."
    assert args.rule_injection in [None, 'full', 'retrieval'], "Either specify an available rule injection option: 'full' / 'retrieval', or leave it as None."

    # Creating the engine.
    engine = generate_engine(engine_name=args.engine_name, model_idx=args.model_idx)

    # Setting the system prompt.
    system_prompt = ' '.join(INSTRUCTION)
    if args.rule_injection == 'full':
        rule_summary = '\n'.join([' '. join(rule) for rule in RULE_SUMMARY])
        system_prompt = f"{system_prompt}Here are the rules of the Labyrinth you should follow.\n{rule_summary}"
    elif args.rule_injection == 'retrieval':
        # TODO: Adding after the RAG method is completed.
        pass

    # Initializing the game manager.
    manager = GameManager(engine=engine, system_prompt=system_prompt)

    if args.eval_name == 'init':
        # Loading the scene file.
        with open("data/scenes.json", 'r') as f:
            scenes = json.load(f)

        assert args.scene_idx is not None, "The scene index should be provided."
        assert 0 <= args.scene_idx < len(scenes), "The scene index is not valid."

        evaluate_init(manager, scenes[args.scene_idx])
    elif args.eval_name == 'rules':
        evaluate_rules(manager)
