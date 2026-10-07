#!/usr/bin/env python3
"""
Script Executor Step - Reference Implementation

Executes Python 3.12 or Bash 5.2 scripts in an isolated container.
Demonstrates the language-agnostic execution contract:
- Validates typed inputs through the SDK base class
- Executes user-provided code
- Returns StandardOutputWrapper
"""

import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Literal

from pydantic import BaseModel, Field
from syntara_sdk import ExecutionContext, TaskStep


def load_inputs() -> dict[str, Any]:
    """Load step inputs from JSON file or stdin."""
    input_path = os.environ.get("NODE_INPUT_PATH", "/tmp/step_input.json")

    if os.path.exists(input_path):
        with open(input_path) as f:
            return json.load(f)

    return json.load(sys.stdin)


def execute_python_script(
    script: str,
    arguments: dict[str, Any],
    env_vars: dict[str, str],
    working_dir: str
) -> dict[str, Any]:
    """
    Execute Python script with named arguments.

    Expects script to define a main() function that accepts kwargs.
    """
    # Inject environment variables
    exec_env = os.environ.copy()
    exec_env.update(env_vars)

    # Create temporary script file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        # Wrap user script to handle arguments and capture output
        wrapper = f'''
import json
import sys

# User script
{script}

# Invoke main() with arguments and capture result
try:
    if 'main' in dir():
        args = {json.dumps(arguments)}
        result = main(**args)
        output = {{
            "return_value": result,
            "stdout": "",
            "stderr": "",
            "exit_code": 0
        }}
        print(json.dumps(output))
        sys.exit(0)
    else:
        print(json.dumps({{
            "return_value": null,
            "stdout": "",
            "stderr": "No main() function found in script",
            "exit_code": 1
        }}))
        sys.exit(1)
except Exception as e:
    print(json.dumps({{
        "return_value": null,
        "stdout": "",
        "stderr": str(e),
        "exit_code": 1
    }}))
    sys.exit(1)
'''
        f.write(wrapper)
        script_path = f.name

    try:
        # Execute script
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=working_dir,
            env=exec_env
        )

        # Parse script output
        try:
            script_output = json.loads(result.stdout)
        except json.JSONDecodeError:
            script_output = {
                "return_value": None,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode
            }

        # Success - return StandardOutputWrapper
        return {
            "Result": script_output,
            "StatusCode": result.returncode,
            "StatusMessage": "Script execution completed" if result.returncode == 0 else "Script execution failed",
            "ErrorMessage": script_output.get("stderr", "")
        }

    except subprocess.TimeoutExpired:
        return {
            "Result": None,
            "StatusCode": 124,
            "StatusMessage": "Script execution timeout",
            "ErrorMessage": "Script exceeded 300 second timeout"
        }

    except Exception as e:
        return {
            "Result": None,
            "StatusCode": 255,
            "StatusMessage": "Script execution error",
            "ErrorMessage": f"{type(e).__name__}: {str(e)}"
        }

    finally:
        os.unlink(script_path)


def execute_bash_script(
    script: str,
    arguments: list,
    env_vars: dict[str, str],
    working_dir: str
) -> dict[str, Any]:
    """
    Execute Bash script with positional arguments.
    """
    # Inject environment variables
    exec_env = os.environ.copy()
    exec_env.update(env_vars)

    # Create temporary script file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write("#!/bin/bash\n")
        f.write("set -euo pipefail\n")  # Strict error handling
        f.write(script)
        script_path = f.name

    # Make executable
    os.chmod(script_path, 0o755)

    try:
        # Execute script with positional arguments
        result = subprocess.run(
            ["/bin/bash", script_path] + arguments,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=working_dir,
            env=exec_env
        )

        # Return StandardOutputWrapper
        return {
            "Result": {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode
            },
            "StatusCode": result.returncode,
            "StatusMessage": "Script execution completed" if result.returncode == 0 else "Script execution failed",
            "ErrorMessage": result.stderr if result.returncode != 0 else ""
        }

    except subprocess.TimeoutExpired:
        return {
            "Result": None,
            "StatusCode": 124,
            "StatusMessage": "Script execution timeout",
            "ErrorMessage": "Script exceeded 300 second timeout"
        }

    except Exception as e:
        return {
            "Result": None,
            "StatusCode": 255,
            "StatusMessage": "Script execution error",
            "ErrorMessage": f"{type(e).__name__}: {str(e)}"
        }

    finally:
        os.unlink(script_path)


def execute_script(inputs: dict[str, Any]) -> dict[str, Any]:
    """Route to Python or Bash executor based on language input."""
    script = inputs["script"]
    language = inputs.get("language", "python3")
    arguments = inputs.get("arguments", {} if language == "python3" else [])
    env_vars = inputs.get("environment_variables", {})
    working_dir = inputs.get("working_directory", "/workspace")

    # Create working directory if it doesn't exist
    os.makedirs(working_dir, exist_ok=True)

    if language == "python3":
        return execute_python_script(script, arguments, env_vars, working_dir)
    elif language == "bash":
        return execute_bash_script(script, arguments, env_vars, working_dir)
    else:
        return {
            "Result": None,
            "StatusCode": 1,
            "StatusMessage": "Unsupported language",
            "ErrorMessage": f"Language '{language}' not supported. Use 'python3' or 'bash'."
        }


class ScriptExecutorInput(BaseModel):
    """Typed inputs mirroring spec.inputs in manifest.yaml."""

    script: str = Field(min_length=1, max_length=1_048_576)
    language: Literal["python3", "bash"] = "python3"
    arguments: dict[str, Any] | list[str] | None = None
    environment_variables: dict[str, str] | None = Field(default=None)
    working_directory: str = "/workspace"


class ScriptExecutorOutput(BaseModel):
    """Inner Result payload; BaseStep wraps it in StandardOutputWrapper."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


class ScriptExecutorStep(TaskStep[ScriptExecutorInput, ScriptExecutorOutput]):
    """Run a Python or Bash script supplied as step input."""

    def __init__(self) -> None:
        super().__init__(ScriptExecutorInput, ScriptExecutorOutput)

    def run(
        self, inputs: ScriptExecutorInput, context: ExecutionContext
    ) -> ScriptExecutorOutput:
        default_args: Any = {} if inputs.language == "python3" else []
        envelope = execute_script(
            {
                "script": inputs.script,
                "language": inputs.language,
                "arguments": inputs.arguments if inputs.arguments is not None else default_args,
                "environment_variables": inputs.environment_variables or {},
                "working_directory": inputs.working_directory,
            }
        )
        if envelope["StatusCode"] != 0:
            raise RuntimeError(envelope["ErrorMessage"] or envelope["StatusMessage"])
        result = envelope["Result"] or {}
        return ScriptExecutorOutput(
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            exit_code=result.get("exit_code", 0),
        )


def main() -> int:
    """Local convenience runner; the platform loads ScriptExecutorStep directly."""

    raw = json.load(sys.stdin)
    output = ScriptExecutorStep().execute_raw(raw)
    print(json.dumps(output.model_dump(), indent=2))
    return output.StatusCode


if __name__ == "__main__":
    sys.exit(main())
