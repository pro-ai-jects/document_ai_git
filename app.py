from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from azure.cosmos import CosmosClient
import os
import datetime
import pyodbc
from operations import process_pdf_to_text, extract_key_value_pairs, perform_word_embedding, search_similar_documents
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_secret_key')  # Use environment variable

# Configure folders
UPLOAD_FOLDER = 'uploads/'
IMAGE_FOLDER = 'images/'
OUTPUT_TEXT_FOLDER = 'output_text/'
OUTPUT_JSON_FOLDER = 'output_json/'
for folder in [UPLOAD_FOLDER, IMAGE_FOLDER, OUTPUT_TEXT_FOLDER, OUTPUT_JSON_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['IMAGE_FOLDER'] = IMAGE_FOLDER

# Azure Cosmos DB configuration
COSMOS_ENDPOINT = os.environ.get('COSMOS_ENDPOINT')
COSMOS_KEY = os.environ.get('COSMOS_KEY')
COSMOS_DB_NAME = os.environ.get('COSMOS_DB_NAME')
COSMOS_CONTAINER_NAME = os.environ.get('COSMOS_CONTAINER_NAME')

# Azure SQL connection
AZURE_SQL_CONN_STR = os.environ.get('AZURE_SQL_CONN_STR')

# Initialize Cosmos DB
def initialize_cosmos_container():
    if not all([COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DB_NAME, COSMOS_CONTAINER_NAME]):
        raise ValueError("Cosmos DB configuration is incomplete. Please check your environment variables.")
    
    try:
        client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
        database = client.create_database_if_not_exists(COSMOS_DB_NAME)
        container = database.create_container_if_not_exists(
            id=COSMOS_CONTAINER_NAME,
            partition_key={"paths": ["/partitionKey"], "kind": "Hash"},
        )
        return container
    except Exception as e:
        print(f"Error initializing Cosmos DB: {str(e)}")
        raise

try:
    cosmos_container = initialize_cosmos_container()
except Exception as e:
    print(f"Failed to initialize Cosmos DB container: {str(e)}")
    cosmos_container = None

def get_db_connection():
    if not AZURE_SQL_CONN_STR:
        raise ValueError("Azure SQL connection string is not set. Please check your environment variables.")
    try:
        return pyodbc.connect(AZURE_SQL_CONN_STR)
    except pyodbc.Error as e:
        print(f"Azure SQL connection error: {e}")
        raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM Users WHERE Username = ?", (username,))
        if cursor.fetchone()[0] > 0:
            conn.close()
            return "User already exists!", 400

        hashed_password = generate_password_hash(password)
        cursor.execute("INSERT INTO Users (Username, PasswordHash) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT UserID, PasswordHash FROM Users WHERE Username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session['user'] = username
            session['user_id'] = user[0]
            session['session_id'] = f"{username}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            return redirect(url_for('dashboard'))
        
        return "Invalid username or password!", 401

    return render_template('login.html')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    username = session['user']
    session_id = session.get('session_id')

    if request.method == 'POST':
        try:
            file = request.files['file']
            if file and file.filename.endswith('.pdf'):
                filename = secure_filename(f"{session_id}_{file.filename}")
                pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(pdf_path)

                image_paths, ocr_text_path = process_pdf_to_text(pdf_path, session_id, username)

                with open(ocr_text_path, "r", encoding="utf-8") as text_file:
                    extracted_text = text_file.read()
                if cosmos_container:
                    cosmos_container.upsert_item({
                        "id": f"{session_id}_{os.path.basename(ocr_text_path)}",
                        "partitionKey": username,
                        "text": extracted_text,
                    })

                return jsonify({
                    "message": "File processed successfully!",
                    "pdf_path": pdf_path,
                    "image_paths": image_paths,
                    "ocr_path": ocr_text_path,
                }), 200
            else:
                return jsonify({"error": "Invalid file format. Please upload a PDF."}), 400
        except Exception as e:
            print(f"Error processing file: {str(e)}")
            return jsonify({"error": f"An error occurred while processing the file: {str(e)}"}), 500

    return render_template('dashboard.html', username=username)

@app.route('/extract_data', methods=['GET'])
def extract_data():
    if 'user' not in session:
        return redirect(url_for('login'))

    username = session['user']
    session_id = session.get('session_id')

    try:
        if cosmos_container:
            key_value_pairs = extract_key_value_pairs(cosmos_container, username)
            embeddings = perform_word_embedding(key_value_pairs)
            similar_docs = search_similar_documents(embeddings)

            result_path = os.path.join(OUTPUT_JSON_FOLDER, f"{session_id}_results.json")
            with open(result_path, "w", encoding="utf-8") as result_file:
                json.dump(similar_docs, result_file, indent=4, ensure_ascii=False)

            return jsonify({
                "message": "Data extracted and processed successfully!",
                "result_path": result_path,
            }), 200
        else:
            return jsonify({"error": "Cosmos DB not initialized. Data extraction unavailable."}), 500
    except Exception as e:
        error_message = f"Error extracting data: {str(e)}"
        print(error_message)
        return jsonify({"error": error_message}), 500

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('user_id', None)
    session.pop('session_id', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    if not cosmos_container:
        print("Warning: Cosmos DB container is not initialized. Some features may not work.")
    app.run(debug=True)

