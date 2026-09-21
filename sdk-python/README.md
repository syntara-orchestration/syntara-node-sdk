# Syntara SDK

Python SDK for building Syntara automation nodes.

## Installation

```bash
pip install syntara-sdk
```

## Quick Start

```python
from pydantic import BaseModel
from syntara_sdk import ActionNode, ExecutionContext

class MyInput(BaseModel):
    url: str
    method: str = "GET"

class MyOutput(BaseModel):
    status_code: int
    body: str

class MyNode(ActionNode[MyInput, MyOutput]):
    def __init__(self):
        super().__init__(input_model=MyInput, output_model=MyOutput)

    def run(self, inputs: MyInput, context: ExecutionContext) -> MyOutput:
        # Your implementation here
        return MyOutput(status_code=200, body="OK")
```

## Documentation

See the main repository README for complete documentation.
