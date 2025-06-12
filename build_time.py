import subprocess
import time
import os

def run_podman_commands():
    """
    Runs Podman build and run commands and tracks their execution time.
    """
    # Define the Dockerfile path relative to the script's location
    # Assumes the script is run from the directory containing 'jupyter' folder
    dockerfile_path = "jupyter/datascience/ubi9-python-3.11/Dockerfile.cpu"

    # Verify the Dockerfile exists before attempting to build
    if not os.path.exists(dockerfile_path):
        print(f"Error: Dockerfile not found at '{dockerfile_path}'. Please ensure the script is run from the correct directory.")
        return

    # Podman build command
    build_command = [
        "podman", "build",
        "-t", "data-science",
        "-f", dockerfile_path,
        "."
    ]

    print(f"--- Starting Podman Build ---")
    print(f"Command: {' '.join(build_command)}")
    build_start_time = time.time()
    try:
        # Using check=True will raise CalledProcessError if the command fails
        subprocess.run(build_command, check=True, text=True, capture_output=True)
        build_end_time = time.time()
        build_duration = build_end_time - build_start_time
        print(f"--- Podman Build Completed in {build_duration:.2f} seconds ---")
    except subprocess.CalledProcessError as e:
        print(f"Error during Podman Build:")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        print(f"Exited with code: {e.returncode}")
        return # Exit if build fails, as run command will also fail

    # Podman run command
    run_command = [
        "podman", "run",
        "--rm", # Automatically remove the container when it exits
        "-it",  # Allocate a pseudo-TTY and keep STDIN open
        "-p", "8888:8888", # Publish port 8888 from the container to the host
        "localhost/data-science"
    ]

    print(f"\n--- Starting Podman Run ---")
    print(f"Command: {' '.join(run_command)}")
    print("Press Ctrl+C to stop the running container.")
    run_start_time = time.time()
    try:
        # For the run command, we want to allow the output to stream to the console
        # and let the user interact (e.g., see Jupyter logs)
        # Using Popen allows for non-blocking execution if needed, but run is simpler for this case
        subprocess.run(run_command, check=True) # Removed capture_output and text to stream output
        run_end_time = time.time()
        run_duration = run_end_time - run_start_time
        print(f"\n--- Podman Run Completed in {run_duration:.2f} seconds ---")
    except subprocess.CalledProcessError as e:
        print(f"Error during Podman Run:")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        print(f"Exited with code: {e.returncode}")
    except KeyboardInterrupt:
        print("\nPodman Run interrupted by user.")
        run_end_time = time.time()
        run_duration = run_end_time - run_start_time
        print(f"Podman Run ran for {run_duration:.2f} seconds before interruption.")

if __name__ == "__main__":
    run_podman_commands()