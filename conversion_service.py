import subprocess
import shutil
import re
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

CONVERSION_PROMPT_FILE = BASE_DIR / "conversion_prompt.md"

COPILOT_CMD = (
    shutil.which("copilot.cmd")
    or shutil.which("copilot")
)


def load_conversion_prompt():
    """Load the existing SAS-to-Java conversion instructions."""

    if not CONVERSION_PROMPT_FILE.is_file():
        raise FileNotFoundError(
            f"Conversion prompt not found: {CONVERSION_PROMPT_FILE}"
        )

    prompt = CONVERSION_PROMPT_FILE.read_text(
        encoding="utf-8"
    )

    if not prompt.strip():
        raise ValueError("conversion_prompt.md is empty.")

    return prompt


def make_class_name(file_stem):
    """Generate a valid Java class name from the SAS filename."""

    name = re.sub(r"\W", "_", file_stem)

    if not name:
        name = "ConvertedProgram"

    if name[0].isdigit():
        name = "_" + name

    return name


def get_java_code(text):
    """Extract Java code from Copilot's response."""

    blocks = re.findall(
        r"```(?:java)?\s*\n(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    return blocks[-1].strip() if blocks else text.strip()


def convert_sas_code(sas_code, sas_filename):
    """
    Convert SAS source code into Java 21 using GitHub Copilot CLI.

    Returns:
        tuple: (class_name, java_code)
    """

    if not COPILOT_CMD:
        raise RuntimeError(
            "GitHub Copilot CLI was not found in PATH."
        )

    if not sas_code or not sas_code.strip():
        raise ValueError("SAS source code is empty.")

    class_name = make_class_name(
        Path(sas_filename).stem
    )

    instructions = load_conversion_prompt()

    prompt = (
        "Read the conversion instructions from instructions.md "
        "and the SAS program from source.sas, both in the "
        "current directory. Convert the SAS program according "
        "to those instructions into a complete Java 21 class "
        f"named {class_name}. "
        "Return only the Java code inside one java code block."
    )

    with tempfile.TemporaryDirectory() as temp_folder:

        temp_path = Path(temp_folder)

        (temp_path / "source.sas").write_text(
            sas_code,
            encoding="utf-8"
        )

        (temp_path / "instructions.md").write_text(
            instructions,
            encoding="utf-8"
        )

        result = subprocess.run(
            [
                COPILOT_CMD,
                "-p", prompt,
                "-s",
                "--no-ask-user",
                "--no-custom-instructions"
            ],
            cwd=temp_folder,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600
        )

        if result.returncode != 0:
            error_message = (
                result.stderr.strip()
                or result.stdout.strip()
                or "Unknown Copilot CLI error."
            )

            raise RuntimeError(
                f"Copilot conversion failed: {error_message}"
            )

        java_code = get_java_code(result.stdout)

        if not java_code:
            raise RuntimeError(
                "Copilot returned an empty Java response."
            )

        return class_name, java_code
