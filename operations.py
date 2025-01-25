import os
from pdf2image import convert_from_path
from PIL import Image
import pytesseract
from azure.cosmos import CosmosClient
from transformers import AutoTokenizer, AutoModel
import faiss
import numpy as np
import operations
import json


OUTPUT_TEXT_FOLDER = os.getenv('OUTPUT_TEXT_FOLDER')
os.makedirs(OUTPUT_TEXT_FOLDER, exist_ok=True)




def convert_pdf_to_images(pdf_path, session_id, username):
    user_image_folder = os.path.join("images", username)
    os.makedirs(user_image_folder, exist_ok=True)  # Ensure the user's image folder exists

    images = convert_from_path(pdf_path)
    image_paths = []

    for i, image in enumerate(images):
        image_filename = f"{session_id}_page_{i + 1}.png"
        image_path = os.path.join(user_image_folder, image_filename)
        image.save(image_path, "PNG")
        image_paths.append(image_path)

    return image_paths

def extract_text_from_images(image_paths):
    extracted_text = ""
    for image_path in image_paths:
        text = pytesseract.image_to_string(Image.open(image_path), lang="eng")
        extracted_text += f"\n--- Text from {os.path.basename(image_path)} ---\n{text}\n"
    return extracted_text

def process_pdf_to_text(pdf_path, session_id, username):
    image_paths = convert_pdf_to_images(pdf_path, session_id, username)
    extracted_text = extract_text_from_images(image_paths)
    ocr_text_path = os.path.join(OUTPUT_TEXT_FOLDER, f"{session_id}_ocr.txt")
    with open(ocr_text_path, "w", encoding="utf-8") as text_file:
        text_file.write(extracted_text)
    return image_paths, ocr_text_path

def extract_key_value_pairs(cosmos_container, username):
    query = f"SELECT * FROM c WHERE c.partitionKey = '{username}'"
    items = list(cosmos_container.query_items(query=query, enable_cross_partition_query=True))
    key_value_pairs = {item['id']: item['text'] for item in items}
    return key_value_pairs

def perform_word_embedding(key_value_pairs):
    tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
    model = AutoModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = {}
    for key, value in key_value_pairs.items():
        inputs = tokenizer(value, return_tensors="pt", padding=True, truncation=True)
        outputs = model(**inputs)
        embeddings[key] = outputs.last_hidden_state.mean(dim=1).detach().numpy()
    return embeddings

def search_similar_documents(embeddings):
    keys = list(embeddings.keys())
    values = np.vstack(list(embeddings.values()))
    index = faiss.IndexFlatL2(values.shape[1])
    index.add(values)
    D, I = index.search(values, 5)
    similar_docs = {keys[i]: [keys[j] for j in I[i]] for i in range(len(keys))}
    return similar_docs


# def extract_data_from_cosmosdb(cosmos_container, username):
#     query = f"SELECT * FROM c WHERE c.username = '{username}'"
#     data = cosmos_container.query_items(query, enable_cross_partition_query=True)
#     return data

def extract_data_from_output_text_folder(output_text_folder):
    data = []
    for file in os.listdir(output_text_folder):
        file_path = os.path.join(output_text_folder, file)
        with open(file_path, 'r') as f:
            file_contents = f.read()
            if file_contents.strip() != '':  # Check if file is not empty
                try:
                    data.append(json.load(f))
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON file {file_path}: {e}")
    return data