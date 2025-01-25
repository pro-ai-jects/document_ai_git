import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER')
    IMAGE_FOLDER = os.getenv('IMAGE_FOLDER')
    OUTPUT_TEXT_FOLDER = os.getenv('OUTPUT_TEXT_FOLDER')
    COSMOS_ENDPOINT = os.getenv('COSMOS_ENDPOINT')
    COSMOS_KEY = os.getenv('COSMOS_KEY')
    COSMOS_DB_NAME = os.getenv('COSMOS_DB_NAME')
    COSMOS_CONTAINER_NAME = os.getenv('COSMOS_CONTAINER_NAME')
    AZURE_SQL_CONN_STR = os.getenv('AZURE_SQL_CONN_STR')