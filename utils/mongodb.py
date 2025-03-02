from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

class MongoDB:
    _instance = None
    _client = None
    _db = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if MongoDB._client is None:
            MongoDB._client = MongoClient(os.getenv("MONGO_URI"))
            MongoDB._db = MongoDB._client['FYP']

    @property
    def db(self):
        return MongoDB._db

    def get_collection(self, collection_name):
        return self.db[collection_name]

# Global instance
mongo_db = MongoDB.get_instance()