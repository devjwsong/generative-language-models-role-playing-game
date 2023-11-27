from agents.manager import GameManager
from agents.kani_models import generate_engine
from utils import select_options, check_init_types
from constants import INSTRUCTION, RULE_SUMMARY
from typing import Dict

import asyncio
import argparse
import json
import logging

log = logging.getLogger("kani")
message_log = logging.getLogger("kani.messages")


def evaluate_init(manager: GameManager, scene: Dict):
    async def test():
        try:
            await manager.init_scene(scene)
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
    parser.add_argument('--concat_policy', type=str, default='simple', help="The concatenation policy for including the previous chat logs.")
    parser.add_argument('--max_turns', type=int, default=None, help="The maximum number of turns to be included. If it is None, the model includes as many turns as possible.")
    parser.add_argument('--summarization', action='store_true', help="Specifying either including the summarization or not.")
    parser.add_argument('--summ_period', type=int, default=None, help="The summarization period. If it is None, all logs are summarized regardless of the concatenation policy.")
    parser.add_argument('--clear_raw_logs', action='store_true', help="Specifying if the raw chat logs are cleared after the summarization.")

    args = parser.parse_args()

    assert args.eval_name in ['init', 'rules'], "Specify the correct evaluation name."
    assert args.rule_injection in [None, 'full', 'retrieval'], "Either specify an available rule injection option: 'full' / 'retrieval', or leave it as None."

    # Creating the engine.
    engine = generate_engine(engine_name=args.engine_name, model_idx=args.model_idx)

    # Setting the system prompt.
    system_prompt = ' '.join(INSTRUCTION)
    if args.rule_injection == 'full':
        rule_summary = '\n'.join([' '. join(rule) for rule in RULE_SUMMARY])
        system_prompt = f"{system_prompt}\nHere are the rules of the Labyrinth you should follow.\n{rule_summary}"
    elif args.rule_injection == 'retrieval':
        # TODO: Adding after the RAG method is completed.
        pass

    # Initializing the game manager.
    manager = GameManager(
        main_args=args,
        encoder=None,
        engine=engine, 
        system_prompt=system_prompt
    )

    if args.eval_name == 'init':
        # Loading the scene file.
        with open("data/scenes.json", 'r') as f:
            scenes = json.load(f)

        assert args.scene_idx is not None, "The scene index should be provided."
        assert 0 <= args.scene_idx < len(scenes), "The scene index is not valid."

        evaluate_init(manager, scenes[args.scene_idx])
    elif args.eval_name == 'rules':
        evaluate_rules(manager)
