# test_mistral.py
from run_model import call_local_llm

test_prompts = ["What is 2+2?", "Tell me about the weather", "Explain machine learning"]

for prompt in test_prompts:
    print(f"\nTesting prompt: {prompt}")
    response = call_local_llm(prompt)
    print(f"Response: {response}")
    print("-" * 50)
