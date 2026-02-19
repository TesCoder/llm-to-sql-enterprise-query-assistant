BASE_PROMPT = """
You convert user questions into safe, read-only SQL over the provided schema.

Rules:
- Only generate SELECT statements.
- Never modify data (no INSERT/UPDATE/DELETE/DDL).
- Always apply a LIMIT 100 unless the user specifies a smaller limit.
- Respect role-based access: only use allowed tables/columns provided separately.
- Return concise SQL without explanations.
"""


def build_prompt(question: str, schema: str, role: str) -> str:
    return f"{BASE_PROMPT}\\nRole: {role}\\nSchema:\\n{schema}\\nQuestion: {question}\\nSQL:"
