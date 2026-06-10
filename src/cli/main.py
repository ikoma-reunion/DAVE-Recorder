import sys
import os
import signal
import logging
import argparse
from PySide6.QtCore import QCoreApplication, QTimer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.process_manager import ProcessManager
from core.settings import SettingsManager
from cli.app import CliApp

def setup_logging(level):
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

def parse_args():
    parser = argparse.ArgumentParser(description="Dave Recorder CLI - Discord E2EE Audio Dumper")
    parser.add_argument("--out-dir", type=str, help="Directory to save recordings")
    parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    parser.add_argument("--subfolders", action="store_true", help="Create subfolders per user")
    parser.add_argument("--timeout", type=int, default=0, help="Automatically exit after N seconds")
    return parser.parse_args()

def main():
    args = parse_args()

    settings = SettingsManager.get_instance()
    if args.out_dir:
        settings.set("save_directory", os.path.abspath(args.out_dir))
    if args.subfolders:
        settings.set("create_subfolders", True)
    settings.set("log_level", args.log_level)

    setup_logging(args.log_level)
    logger = logging.getLogger("CLI")

    q_app = QCoreApplication(sys.argv)

    instances = ProcessManager.get_discord_instances()
    if not instances:
        logger.error("No Discord instances found. Please join a voice channel.")
        sys.exit(1)

    if '__compiled__' in globals() or getattr(sys, 'frozen', False):
        scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'frida_scripts')
    else:
        scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src', 'frida_scripts')

    cli_app = CliApp(instances, scripts_dir)
    cli_app.start()

    if not cli_app.managers:
        logger.error("Failed to attach to any Discord instances.")
        sys.exit(1)

    # Inactivity timer
    timer = QTimer()
    timer.timeout.connect(cli_app.check_inactivity)
    timer.start(500)

    def signal_handler(sig, frame):
        logger.info("\nCtrl+C detected. Shutting down gracefully...")
        cli_app.stop()
        q_app.quit()

    signal.signal(signal.SIGINT, signal_handler)

    # Required for Windows to allow SIGINT to interrupt the Qt Event Loop
    import platform
    if platform.system() == "Windows":
        timer_sigint = QTimer()
        timer_sigint.timeout.connect(lambda: None)
        timer_sigint.start(200)

    if args.timeout > 0:
        def auto_quit():
            logger.info(f"Timeout of {args.timeout} seconds reached. Exiting...")
            cli_app.stop()
            q_app.quit()
        QTimer.singleShot(args.timeout * 1000, auto_quit)

    logger.info("Dave Recorder CLI is running. Press Ctrl+C to stop.")
    sys.exit(q_app.exec())

if __name__ == "__main__":
    main()
