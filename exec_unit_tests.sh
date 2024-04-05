python src/evaluation/run_unit_tests.py \
    --model_idx=MODEL_IDX \
    --rule_injection=full \
    --tests_path=TESTS_PATH \
    --result_dir=unit_test_results \
    --concat_policy=simple \
    --include_functions \
    --include_rules \
    --include_scene_state \
    --include_player_states \
    --frequency_penalty=0.5 \
    --presence_penalty=0.5 \
    --temperature=0.5 \
    --top_p=1.0