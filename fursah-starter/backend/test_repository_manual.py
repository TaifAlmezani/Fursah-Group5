# Import the project's settings.
from app.infrastructure.data_package import Settings

# Import the real dataset loader.
from app.infrastructure.data_package import DatasetLoader

# Import the repository we want to test.
from app.repository import OpportunityRepository


# STEP 1: Load project settings.
settings = Settings()

# STEP 2: Create the dataset loader.
loader = DatasetLoader(settings)

# STEP 3: Create the repository.
repository = OpportunityRepository(loader)


# TEST 1: Check the data directory.
print("Data directory:", settings.data_dir)


# TEST 2: Load real opportunity records.
records = repository._load_records()

print("\nTotal loaded records:", len(records))


# TEST 3: Check repository readiness.
print("\nRepository ready:", repository.is_ready())


# TEST 4: Retrieve an opportunity.
result = repository.get_details("SRC-0001")

print("\nOpportunity details:")

if result:
    print(result.model_dump())
else:
    print("Opportunity not found")

import json

# Get the original prepared record.
record = next(
    (
        row
        for row in records
        if repository._record_id(row) == "SRC-0001"
    ),
    None,
)

print("\nORIGINAL RECORD:")
print(
    json.dumps(
        record,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
)