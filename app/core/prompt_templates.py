# Akshay-core
__author__ = "Akshay-core"

# FILE: app/core/prompt_templates.py

SYSTEM_PROMPT = """You are an intelligent AI assistant with access to the user's personal knowledge base.
You answer questions accurately using the provided context.
If the context doesn't contain enough information, say so honestly.
Always cite your sources when using retrieved information.
You may connect concepts across documents, but every factual claim must be grounded in supplied evidence or clearly marked as a hypothesis.
Do not invent page details, source contents, memories, or relationships that are not present in the supplied context.
Be concise, grounded, and direct."""

RAG_TEMPLATE = """Use the following context from the user's documents to answer their question.

CONTEXT FROM KNOWLEDGE BASE:
{context}

USER QUESTION: {question}

Instructions:
- Answer based primarily on the provided context
- If context is insufficient, clearly state that
- Cite source files when referencing specific information
- Be precise and helpful
- Do not invent details not supported by the context

ANSWER:"""

LOW_CONFIDENCE_RAG_TEMPLATE = """The retrieved context may be incomplete. Answer carefully and make uncertainty visible.

CONTEXT FROM KNOWLEDGE BASE:
{context}

USER QUESTION: {question}

Instructions:
- Start with the most likely answer if the evidence supports one
- Clearly say what is uncertain or missing
- Cite source files for supported claims
- Avoid unsupported claims

ANSWER:"""

CHAT_ONLY_TEMPLATE = """You are a helpful AI assistant.

Previous conversation:
{history}

User: {message}
Assistant:"""

QUIZ_TEMPLATE = """Based on the following content, generate {count} exam-style questions with answers.

CONTENT:
{content}

Format each question as:
Q[N]: <question>
A[N]: <answer>

Generate {count} questions now:"""

SUMMARIZE_TEMPLATE = """Summarize the following document content concisely.
Highlight key concepts, main ideas, and important details.

CONTENT:
{content}

SUMMARY:"""
