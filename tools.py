from langchain_core.tools import tool
from github import Github, Auth
from dotenv import load_dotenv
from uuid import uuid4
import subprocess
import git
import os
import shutil
import stat

load_dotenv()
FILE_TYPES = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.cpp', '.c', '.h', '.hpp', 
        '.md', '.txt', '.json', '.html', '.css', '.java', '.go', '.rs'
    }
IGNORED_DIRS =  {'.git', '.venv', 'venv', 'env', 'node_modules', '__pycache__', 'build', 'dist', '.idea', '.vscode'}
INFO_DIRS = ["README.md", "readme.md", "requirements.txt", "package.json"]
NPX_COMMAND = ["npx", "-y", "repomix@latest"]
NPX_SHALLOW_COMMAND = ["npx", "-y", "repomix@latest", "--include", "README.md,docs/**,architecture.md,requirements.txt,package.json"]
POSSIBLE_REPOMIX = ["repomix-output.xml", "repomix-output.txt", "repomix-output.md"]
CREATE_NO_WINDOW = 0x08000000
GIT_KEY = os.getenv("GIT_HUB_TOKEN")
AUTO = Auth.Token(GIT_KEY)

@tool
def list_repositories(dummy_input: str = "") -> str:
    """Fetches a list of all public and private repository names owned by the authenticated user.
    This tool requires NO real input. If prompted for an input, pass an empty string."""
    g = Github(auth=AUTO)
    repos = [repo.full_name for repo in g.get_user().get_repos(type="owner")]
    return f"Repositories found: {', '.join(repos)}"

@tool
def list_branches(repo_name: str) -> str:
    """Fetches all branch names for a specific repository. Input MUST be formatted as 'username/repo-name'."""
    g = Github(auth=AUTO)
    try:
        repo = g.get_repo(repo_name)
        branches = [branch.name for branch in repo.get_branches()]
        return f"Branches for {repo_name}: {', '.join(branches)}"
    except Exception as e:
        return f"Error finding repository {str(e)}"

@tool
def check_repo_visibility(repo_name: str) -> str:
    """
    Check whether a specific GitHub repository is public or private
    Input MUST be the full repository name formatted as 'owner/repo_name'
    """
    g = Github(auth=AUTO)
    try:
        repo = g.get_repo(repo_name)
        if repo.private:
            return f"The repository '{repo_name}' is PRIVATE."
        else:
            return f"The repository '{repo_name}' is PUBLIC."
    except Exception as e:
        return f"Error finding repository {str(e)}"
    

@tool
def clone_repository(repo_url_or_name: str = "") -> str:
    """
    Clones a GitHub repository to a local temporary directory. 
    Accepts full URLs (https://github.com/user/repo) or short formats (user/repo).
    Returns the exact local directory path where the repo was cloned.
    """
    url = repo_url_or_name
    if not repo_url_or_name.startswith("http"):
        url = f"https://{GIT_KEY}@github.com/{repo_url_or_name}.git"
    
    id = str(uuid4())[:8]
    path = os.path.abspath(f"./temp_repo_{id}")
    
    try:
        git.Repo.clone_from(url, path)
        return f"Success: Cloned to local path: '{path}'. Use this path for subsequent operations."
    except Exception as e:
        return f"Error cloning repository: {str(e)}"
    
@tool
def summarize_and_analyzes_cloned_repo(repo_clone_folder: str, mode: str = "deep") -> str:
    """
    Analyzes a locally cloned repository directory.
    and generates packed summary of the entire codebase
    Input must be the local directory path of the cloned repository.
    """
    if not os.path.exists(repo_clone_folder) or not os.path.isdir(repo_clone_folder):
        return f"Error: Directory '{repo_clone_folder}' does not exist."
    
    try:
        if mode == "shallow":
            cmd = NPX_SHALLOW_COMMAND
        else:
            cmd = NPX_COMMAND
        result = subprocess.run(
            cmd,
            cwd=repo_clone_folder,
            capture_output=True,
            text=True,
            shell=True,
            timeout=180,
            creationflags=CREATE_NO_WINDOW,
        )
        
        if result.returncode != 0:
            return f"Error running repomix. Is Node.js installed?\nStderr: {result.stderr}"
        output_file_path = None
        for filename in POSSIBLE_REPOMIX:
            target_path = os.path.join(repo_clone_folder, filename)
            if os.path.exists(target_path):
                output_file_path = target_path
                break
            
        if not output_file_path:
            return f"Repomix executed, but no output file was found.\nStdout: {result.stdout}"
        with open(output_file_path, "r", encoding="utf-8", errors="ignore") as f:
            repomix_content = f.read()
    
        return f"Repomix successfully packed the repository into XML. Here is the data:\n\n{repomix_content}"
    except subprocess.TimeoutExpired:
        return "Error: Repomix took too long to execute and was killed."
    except Exception as e:
        return f"System error executing repomix: {str(e)}"
    
@tool
def delete_all_repository_folders(dummy_input: str = "") -> str:
    """
    Deletes all of the repository clone folders that were cloned.
    This tool requires NO real input. If prompted for an input, pass an empty string.
    """

    def remove_readonly(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    for f in os.listdir():
        if (not os.path.isfile(os.path.join(f)) and "temp_repo_" in f):
            try:
                shutil.rmtree(f, onerror=remove_readonly)
            except Exception as e:
                return f"Could not delete file {f}"
    return "RECEIPT: FOLDERS_DELETED_SUCCESSFULLY"
