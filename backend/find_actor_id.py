import os
from apify_client import ApifyClient
from dotenv import load_dotenv

# Try loading from .env in current dir or backend/
load_dotenv()
load_dotenv('backend/.env')

def main():
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        print("Error: APIFY_API_TOKEN not found in env.")
        return

    client = ApifyClient(token)
    
    print("Listing actors...")
    try:
        # iterate_list behaves like a generator
        for actor in client.actors().list().items:
            print(f"Name: {actor.get('name')} | ID: {actor.get('id')} | Title: {actor.get('title')}")
    except Exception as e:
        print(f"Error listing actors: {e}")

if __name__ == "__main__":
    main()
