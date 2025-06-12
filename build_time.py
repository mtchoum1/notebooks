import subprocess
import time
import os

def run_podman_commands_repeated_build():
    """
    Runs Podman build command ten times and then the run command once,
    tracking their execution times.
    """
    # Define the Dockerfile path relative to the script's location
    dockerfile_path = "jupyter/minimal/ubi9-python-3.11/Dockerfile.cpu"

    # Verify the Dockerfile exists before attempting to build
    if not os.path.exists(dockerfile_path):
        print(f"Error: Dockerfile not found at '{dockerfile_path}'. "
              "Please ensure the script is run from the correct directory "
              "containing the 'jupyter' folder.")
        return

    # Podman build command
    build_command = [
        "podman", "build",
        "-t", "minimal",
        "-f", dockerfile_path,
        "."
    ]

    build_durations = []
    num_builds = 10

    print(f"--- Starting {num_builds} Podman Builds ---")
    for i in range(1, num_builds + 1):
        print(f"\n--- Podman Build {i}/{num_builds} ---")
        print(f"Command: {' '.join(build_command)}")
        build_start_time = time.time()
        try:
            # Using check=True will raise CalledProcessError if the command fails
            # capture_output=True prevents build logs from cluttering the console for repeated builds
            # and allows checking stdout/stderr if needed
            subprocess.run(build_command, check=True, text=True, capture_output=True)
            build_end_time = time.time()
            duration = build_end_time - build_start_time
            build_durations.append(duration)
            print(f"Podman Build {i} Completed in {duration:.2f} seconds.")
        except subprocess.CalledProcessError as e:
            print(f"Error during Podman Build {i}:")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            print(f"Exited with code: {e.returncode}")
            print("Aborting subsequent builds and run due to build failure.")
            return # Exit if any build fails

    if build_durations:
        avg_build_duration = sum(build_durations) / len(build_durations)
        print(f"\n--- All {num_builds} Podman Builds Completed ---")
        print(f"Individual build times: {[f'{d:.2f}s' for d in build_durations]}")
        print(f"Average build time: {avg_build_duration:.2f} seconds")
    else:
        print("\nNo successful builds were completed.")
        return # No point in running if builds failed/didn't happen

if __name__ == "__main__":
    run_podman_commands_repeated_build()