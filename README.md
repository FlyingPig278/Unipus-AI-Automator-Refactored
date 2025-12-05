# Setup Guide

## Prerequisites

- **Python**: Python 3.13 is recommended. Python 3.12 is untested. **Do not use Python 3.14 or newer.**
- During Python installation, ensure you check the box that says **"Add Python to PATH"**.
- **Git**: You need Git installed to clone the repository.

## Installation Steps

1.  **Clone the repository**

    Open your terminal or command prompt and run the following command:

    ```bash
    git clone <your-repository-url-here>
    cd <repository-folder-name>
    ```
    
    *If `git clone` is not working or you prefer, you can also download the project as a ZIP file from the repository page and extract it manually.*

2.  **Create and activate a virtual environment**

    This keeps the project's dependencies isolated.

    ```bash
    # Create the virtual environment
    python -m venv .venv
    ```

    Now, activate it:
    -   **On Windows (Command Prompt or PowerShell):**
        ```cmd
        .\.venv\Scripts\activate
        ```
    -   **On macOS/Linux (Bash/Zsh):**
        ```bash
        source .venv/bin/activate
        ```
    You will see `(.venv)` at the beginning of your terminal prompt if it's activated correctly.

3.  **Install dependencies**

    The required packages are listed in `requirements.txt`. Installation can be slow due to the size of the packages. Using a mirror is highly recommended for faster downloads.

    -   **Option A (Standard Pip):**
        ```bash
        pip install -r requirements.txt
        ```

    -   **Option B (Recommended for faster download speeds):**
        This uses a popular mirror to accelerate the download.
        ```bash
        pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        ```
        
4.  **Install browser binary**

    This project uses Playwright, which needs a browser to operate. To minimize download size, you only need to install Chromium.

    ```bash
    playwright install chromium
    ```

5.  **Configure environment variables**

    The application requires credentials and API keys to run.

    -   Find the file named `.env.example` and rename it to `.env`.
    -   Open the `.env` file with a text editor.
    -   Fill in the required values for `U_USERNAME`, `U_PASSWORD`, and `DEEPSEEK_API_KEY`. (You can apply for a DeepSeek API key at https://platform.deepseek.com/api_keys).

6.  **Run the application**

    Once all the steps above are completed, you can run the script:

    ```bash
    python main.py
    ```
