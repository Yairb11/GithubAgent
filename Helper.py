def get_promot(prompt_name):
    """Gets prompt name and returns the full prompt from the saved {prompt}.txt file

    Args:
        prompt_name (string): prompt name

    Returns:
        string: full prompt
    """
    prompt = ""
    with open(f"prompts/{prompt_name}.txt", "r", encoding="utf-8") as file:
        prompt = file.read()
    return prompt
