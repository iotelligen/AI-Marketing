
import os

from litellm import embedding


EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "openai/text-embedding-3-small",
)

BATCH_SIZE = int(
    os.getenv("EMBEDDING_BATCH_SIZE", "64")
)


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings in batches.

    Preserves the original input ordering.
    """

    if not texts:
        return []

    if BATCH_SIZE < 1:
        raise ValueError("EMBEDDING_BATCH_SIZE must be positive")

    all_vectors = []

    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]

        response = embedding(
            model=EMBEDDING_MODEL,
            input=batch,
        )

        batch_vectors = [
            item["embedding"]
            for item in sorted(
                response.data,
                key=lambda item: item["index"],
            )
        ]

        if len(batch_vectors) != len(batch):
            raise RuntimeError(
                "Embedding response count does not match input count"
            )

        all_vectors.extend(batch_vectors)

    return all_vectors
