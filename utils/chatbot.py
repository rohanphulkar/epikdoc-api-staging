import faiss
import pickle
from sentence_transformers import SentenceTransformer
import os

# Get absolute path to chatbot model directory
CHATBOT_MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "chatbot_model"))

# Load the chatbot model
def load_chatbot_model():
    embedding_model = SentenceTransformer(os.path.join(CHATBOT_MODEL_DIR, "sentence_transformer"))
    index = faiss.read_index(os.path.join(CHATBOT_MODEL_DIR, "faiss_index"))

    with open(os.path.join(CHATBOT_MODEL_DIR, "metadata.pkl"), "rb") as file:
        metadata = pickle.load(file)

    questions = metadata["questions"]
    answers = metadata["answers"]

    return embedding_model, index, questions, answers

embedding_model, index, questions, answers = load_chatbot_model()

# Get the closest answer to a query
def get_answer(query):
    query_embedding = embedding_model.encode([query])
    _, closest_idx = index.search(query_embedding, 1)

    closest_question = questions[closest_idx[0][0]]
    return answers[closest_question]