def get_promot(prompt_name):
    prompt = ""
    with open(f"prompts/{prompt_name}.txt", "r", encoding="utf-8") as file:
        prompt = file.read()
    return prompt
