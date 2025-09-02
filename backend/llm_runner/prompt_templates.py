# backend/llm_runner/prompt_templates.py

def build_onboarding_prompt(
    user_message: str,
    context: str = "",
    registration_data: dict = None
) -> str:
    onboarding_step = "welcome"
    if context.startswith("Onboarding Step:"):
        onboarding_step = context.split("\n")[0].split(":")[1].strip()

    # Build registration details string
    reg_details = ""
    if registration_data:
        reg_details = (
            f"- Name: {registration_data.get('name')}\n"
            f"- Date of Birth: {registration_data.get('dob')}\n"
            f"- Phone Number: {registration_data.get('phone_number')}\n"
            f"- Email: {registration_data.get('email')}\n"
            f"- Business Name: {registration_data.get('business_name')}\n"
            f"- Account Type: {registration_data.get('account_type')}\n"
            f"- Ownership Type: {registration_data.get('ownership_type')}\n"
            f"- Partnership Details: {registration_data.get('partnership_details')}\n"
            f"- Expected Annual Turnover: {registration_data.get('annual_turnover')}\n"
            f"- Above 18: {'Yes' if registration_data.get('is_above_18') else 'No'}\n"
        )

    # Document instructions based on account type
    account_type = registration_data.get('account_type') if registration_data else None
    if onboarding_step == "welcome":
        if account_type == "Savings":
            instructions = "Please submit your Emirates ID and Commercial License as image files."
        elif account_type == "Corporate":
            instructions = "Please submit your Emirates ID, Commercial License, and Trade License as image files."
        else:
            instructions = "Please submit your documents as image files to continue onboarding."
    elif onboarding_step == "document_verification":
        instructions = (
            "Inform the user that all relevant documents have been received and are being verified. Ask if they have any other queries."
        )
    elif onboarding_step == "verification_complete":
        instructions = (
            "Congratulate the user for being onboarded and inform them that account details will be shared within 3-4 business days."
        )
    else:
        instructions = "Respond helpfully to the user's query."

    prompt = f"""
You are an intelligent and friendly onboarding assistant at Thrivv.

Current onboarding step: {onboarding_step}
Instructions: {instructions}

User registration details:
{reg_details}

Here is a question from the user:
\"\"\"{user_message}\"\"\"

Relevant background information:
\"\"\"{context}\"\"\"

Please respond in a helpful, conversational tone.
"""
    return prompt.strip()

