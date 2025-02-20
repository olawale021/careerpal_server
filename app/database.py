from databases import Database
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get the database URL from environment variables
DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL")

# Create a new Database instance with statement_cache_size set to 0
database = Database(DATABASE_URL, min_size=1, max_size=5, statement_cache_size=0)

# Add connect and disconnect methods
async def connect():
    """Connect to the database."""
    try:
        await database.connect()
        print("Successfully connected to database")
    except Exception as e:
        print(f"Error connecting to database: {str(e)}")
        raise e

async def disconnect():
    """Disconnect from the database."""
    try:
        await database.disconnect()
        print("Successfully disconnected from database")
    except Exception as e:
        print(f"Error disconnecting from database: {str(e)}")
        raise e

async def fetch_val(query: str, values: dict = None):
    """Execute a query and return a single value."""
    try:
        result = await database.fetch_one(query=query, values=values)
        return result[0] if result else 0
    except Exception as e:
        print(f"Error fetching value: {str(e)}")
        return 0

async def execute_many(query: str, values: list):
    """Execute a query with multiple sets of values."""
    try:
        async with database.transaction():
            for value in values:
                await database.execute(query=query, values=value)
        print(f"Successfully inserted {len(values)} records")
    except Exception as e:
        print(f"Error executing batch query: {str(e)}")
        raise e
