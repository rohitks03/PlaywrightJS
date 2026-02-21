import os
import socket
import csv
import sys
import logging
import subprocess
import json
import copy
import shutil
from shutil import move
import time
import tempfile
from typing import Dict, List, Optional, Any
from app.util import helper_functions
import simulation as sim
import result_comparison as res

# -*- coding: utf-8 -*-
"""
Automation Script (Updated for Ansys Web Licensing + Service Priority)

Key changes:
- Uses Ansys Web Licensing via ANSYS_LICENSING_WEB_ACCOUNTS (no local license file / FlexNet server switching).
- Adds ANSYS_LICENSING_SERVICE_PRIORITY = "web-shared,fnp,web-elastic".
- Removes file/server license swapping; keeps robust Results copy and error handling.
- pos_simulation does not fail if FlexNet log is absent (expected under Web Licensing).

Author: Rohit Kshirsagar (updated with M365 Copilot assistance)
Date: 2026-02-20
"""


# ==============================================================================================
# SECTION 1: IMPORTS & PATH CONFIGURATION
# ==============================================================================================

CUR_PATH = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
sys.path.append(CUR_PATH)

# Internal utilities
try:
except ImportError as e:
    raise ImportError(
        "Missing internal module: app.util.helper_functions. "
        "Ensure PYTHONPATH includes your project root."
    ) from e

# Optional: Swap_Licenses (kept for backward compatibility)
try:
    from app.util import Swap_Licenses as sl  # noqa: F401
except Exception:
    sl = None

# Optional third-party libraries
try:
    import pandas as pd  # noqa: F401
    import numpy as np   # noqa: F401
except Exception:
    pd = None
    np = None


# ==============================================================================================
# SECTION 2: CONFIGURATION & VALIDATION
# ==============================================================================================

class ConfigValidator:
    """Validates and manages configuration arguments."""
    
    REQUIRED_KEYS = ['dst_dir', 'actual_dir', 'project_name']
    
    @staticmethod
    def validate_args(args: Dict[str, Any]) -> None:
        """Validate required arguments are present."""
        missing = [k for k in ConfigValidator.REQUIRED_KEYS if k not in args]
        if missing:
            raise ValueError(f"Missing required arguments: {missing}")
    
    @staticmethod
    def validate_web_account_id(web_uuid: str) -> None:
        """Validate web account ID format."""
        if not web_uuid or not isinstance(web_uuid, str):
            raise ValueError("A valid web_account_id (UUID) is required for Web Licensing.")


def configure_web_licensing(args: Dict[str, Any], logger: logging.Logger) -> None:
    """
    Configure Ansys Web Licensing for this session.

    Args:
        args: Dictionary containing configuration (web_account_id optional).
        logger: Logger instance for output.

    Raises:
        ValueError: If web_account_id is invalid.

    Effect:
        - Sets ANSYS_LICENSING_WEB_ACCOUNTS environment variable.
        - Sets ANSYS_LICENSING_SERVICE_PRIORITY = "web-shared,fnp,web-elastic".
        - Does NOT set FlexNet variables.

    Notes:
        - Under Web Licensing, FlexNet checkout logs may be absent.
        - pos_simulation() is adapted to handle this gracefully.
    """
    # Use provided UUID or fallback to known default
    web_uuid = args.get(
        "web_account_id",
        "bf89e499-5997-4b42-b987-054ba153ab78"
    )

    # Validate UUID
    ConfigValidator.validate_web_account_id(web_uuid)

    # Configure Web Licensing
    os.environ["ANSYS_LICENSING_WEB_ACCOUNTS"] = web_uuid
    logger.info("Set ANSYS_LICENSING_WEB_ACCOUNTS for Web Licensing.")

    # Set service priority
    os.environ["ANSYS_LICENSING_SERVICE_PRIORITY"] = "web-shared,fnp,web-elastic"
    logger.info("Set ANSYS_LICENSING_SERVICE_PRIORITY=web-shared,fnp,web-elastic")


# ==============================================================================================
# SECTION 3: UTILITY FUNCTIONS
# ==============================================================================================

def _safe_copy_results(src_dir: str, dst_dir: str, logger: logging.Logger) -> None:
    """
    Copy Results directory, merging into destination if it already exists.
    Works across Python versions (3.7+ fallback implemented).

    Args:
        src_dir: Source Results directory path.
        dst_dir: Destination Results directory path.
        logger: Logger instance.
    """
    if not os.path.isdir(src_dir):
        logger.info(f"No Results directory to copy from: {src_dir}")
        return

    os.makedirs(dst_dir, exist_ok=True)

    # Try Python 3.8+ signature
    try:
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)  # type: ignore
        logger.info(f"Copied Results from {src_dir} to {dst_dir}")
        return
    except TypeError:
        # Fallback for older Python versions
        _safe_copy_results_legacy(src_dir, dst_dir, logger)


def _safe_copy_results_legacy(src_dir: str, dst_dir: str, logger: logging.Logger) -> None:
    """
    Legacy implementation for Python < 3.8: merge directories manually.

    Args:
        src_dir: Source Results directory path.
        dst_dir: Destination Results directory path.
        logger: Logger instance.
    """
    for root, dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        target_root = os.path.join(dst_dir, rel) if rel != '.' else dst_dir
        os.makedirs(target_root, exist_ok=True)
        
        for d in dirs:
            os.makedirs(os.path.join(target_root, d), exist_ok=True)
        
        for f in files:
            srcf = os.path.join(root, f)
            dstf = os.path.join(target_root, f)
            try:
                shutil.copy2(srcf, dstf)
            except Exception as e:
                logger.warning(f"Could not copy {srcf} -> {dstf}: {e}")


def clean_temp_folders(logger: logging.Logger) -> None:
    """
    Clean cached .ansys temporary folder.

    Args:
        logger: Logger instance.
    """
    lic_log_dir = os.path.join(tempfile.gettempdir(), '.ansys')
    if os.path.isdir(lic_log_dir):
        try:
            shutil.rmtree(lic_log_dir)
            logger.info('Deleted .ansys folder')
        except Exception as e:
            logger.warning(f"Could not delete {lic_log_dir}: {e}")


# ==============================================================================================
# SECTION 4: WORKFLOW - PRE-SIMULATION
# ==============================================================================================

def pre_simulation(args: Dict[str, Any]) -> bool:
    """
    Pre-simulation setup step.

    Actions:
      - Configure Web Licensing + service priority.
      - Clean .ansys temp folder.

    Args:
        args: Configuration dictionary (must contain 'dst_dir').

    Returns:
        True on success.

    Raises:
        ValueError: If configuration is invalid.
    """
    print('Pre-simulation: Configuring Web Licensing and cleaning temp folders...')
    
    log_file = os.path.join(args['dst_dir'], 'pre_simulation.log')
    logger = helper_functions.get_logger(log_file, logging.INFO)

    try:
        logger.info("---------- Web Licensing Setup Start ----------")
        configure_web_licensing(args, logger)
        logger.info("---------- Web Licensing Setup End ----------")
    except Exception as e:
        logger.error(f"Web Licensing configuration failed: {e}")
        raise

    clean_temp_folders(logger)
    return True


# ==============================================================================================
# SECTION 5: WORKFLOW - MAIN SIMULATION
# ==============================================================================================

def prepare_schematic(oDesktop, params: Dict[str, Any]) -> None:
    """
    Hook to adjust schematic before running simulations.
    Keep it idempotent and side-effect aware in multi-design runs.

    Args:
        oDesktop: Ansys AEDT desktop object.
        params: Project parameters dictionary.
    """
    oProject = oDesktop.GetActiveProject()
    oDesign = oProject.GetActiveDesign()
    _ = oDesign.SetActiveEditor("SchematicEditor")
    # TODO: add any schematic modifications using params if needed


def simulate_and_compare(args: Dict[str, Any], oDesktop) -> None:
    """
    Main simulation and comparison workflow (runs under AEDT/Simplorer host).

    Steps:
      - Build params via simulation.get_project_params
      - Iterate designs, run setups, copy Results per-design
      - Export aggregated summary

    Args:
        args: Configuration dictionary.
        oDesktop: Ansys AEDT desktop object.

    Raises:
        ImportError: If simulation or result_comparison modules are missing.
    """
    # Import simulation modules
    try:
    except ImportError as e:
        raise ImportError(f"Missing required modules: {e}") from e

    # 1) Prepare params and comparison options
    params = sim.get_project_params(oDesktop, args)
    comparison_options = params.get('comparison_options', {})
    comparison_options['Netlist'] = 1
    comparison_options['Simulation'] = 1

    oProject = params['oProject']

    # 2) Prepare schematic
    prepare_schematic(oDesktop, params)

    # 3) Setup logging
    log_file = os.path.join(params['actual_dir'], 'simulate_and_compare.log')
    logger = helper_functions.get_logger(log_file, logging.INFO)

    # 4) Iterate designs and simulate
    project_results = {}
    oProject.UpdateDefinitions()

    for oDesign in params['design_list']:
        design_name = _extract_design_name(oDesign)
        
        try:
            _run_design_simulation(
                oProject, oDesign, design_name, params, sim, res, logger, project_results
            )
            _copy_design_results(oProject, design_name, params, logger)

        except Exception as e:
            msg = f"Unexpected error for design '{design_name}': {e}"
            logger.error(msg)
            project_results[design_name] = res.get_test_result_summary(
                design_name, params, '5', msg
            )
            try:
                oDesign.AddMessage('Error', msg, 2)
            except Exception:
                pass

    # 5) Export aggregated results
    res.export_project_results(project_results, params['actual_dir'])


def _extract_design_name(oDesign) -> str:
    """
    Extract design name from Ansys design object.

    Args:
        oDesign: Ansys design object.

    Returns:
        Design name string (fallback to 'Unknown_Design' on error).
    """
    try:
        raw_name = oDesign.GetName()
        tokens = raw_name.split(';')
        return tokens[1] if len(tokens) > 1 else raw_name
    except Exception:
        return "Unknown_Design"


def _run_design_simulation(
    oProject, oDesign, design_name: str, params: Dict, sim, res, 
    logger: logging.Logger, project_results: Dict
) -> None:
    """
    Run simulation for a single design.

    Args:
        oProject: Ansys project object.
        oDesign: Ansys design object.
        design_name: Name of design.
        params: Project parameters.
        sim: Simulation module.
        res: Result comparison module.
        logger: Logger instance.
        project_results: Dictionary to store results.
    """
    oProject.SetActiveDesign(design_name)
    
    try:
        oDesign.AddMessage('Info', f'########## Current Design: {design_name} #########', 1)
    except Exception:
        pass

    # Check for errors before simulation
    has_errors = sim.search_for_errors_in_message_manager(
        oProject, params['project_name'], design_name
    )
    if has_errors:
        project_results[design_name] = res.get_test_result_summary(
            design_name, params, '5', 'Error Simulate'
        )
        return

    # Run solutions
    design_result = sim.run_solutions_for_design(oProject.GetParent(), oProject, oDesign, params)
    if design_result:
        project_results[design_name] = design_result


def _copy_design_results(
    oProject, design_name: str, params: Dict, logger: logging.Logger
) -> None:
    """
    Copy Results directory for a design.

    Args:
        oProject: Ansys project object.
        design_name: Name of design.
        params: Project parameters.
        logger: Logger instance.
    """
    project_results_folder = os.path.join(oProject.GetPath(), 'Results')
    dest_folder = os.path.join(params['actual_dir'], 'Results', design_name)
    _safe_copy_results(project_results_folder, dest_folder, logger)


# ==============================================================================================
# SECTION 6: WORKFLOW - POST-SIMULATION
# ==============================================================================================

class LicenseLogAnalyzer:
    """Analyzes FlexNet license logs."""
    
    @staticmethod
    def read_license_log(lic_log_file: str, logger: logging.Logger) -> List[str]:
        """
        Extract license strings from FlexNet log.

        Args:
            lic_log_file: Path to license log.
            logger: Logger instance.

        Returns:
            List of license strings found.
        """
        test_lic = []
        if not os.path.isfile(lic_log_file):
            logger.info(f"License log not found: {lic_log_file}")
            return test_lic

        try:
            with open(lic_log_file, encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if 'CHECKOUT' in line:
                        try:
                            lic_string = line.split('CHECKOUT', 1)[1].split()[0].strip()
                            if lic_string:
                                test_lic.append(lic_string)
                        except Exception:
                            continue
        except Exception as e:
            logger.error(f"Failed reading license log: {e}")

        return test_lic

    @staticmethod
    def compare_licenses(
        gold_lic: List[str], test_lic: List[str], logger: logging.Logger
    ) -> Optional[Dict[str, List[str]]]:
        """
        Compare gold and test license sets.

        Args:
            gold_lic: Gold license list.
            test_lic: Test license list.
            logger: Logger instance.

        Returns:
            Dict with 'missing' and 'extras' keys, or None if match.
        """
        gold_set = set(gold_lic)
        test_set = set(test_lic)

        logger.info(f"Gold License Strings: {sorted(gold_set)}")
        logger.info(f"Test License Strings: {sorted(test_set)}")

        if test_set == gold_set:
            logger.info("License strings match the gold set.")
            return None

        missing = sorted(gold_set - test_set)
        extras = sorted(test_set - gold_set)
        logger.info(f"License mismatch - Missing={missing} Extras={extras}")
        
        return {'missing': missing, 'extras': extras}


def _annotate_summary_with_license_mismatch(
    summary_file: str, mismatch: Dict[str, List[str]], logger: logging.Logger
) -> None:
    """
    Annotate summary.json with license mismatch details.

    Args:
        summary_file: Path to summary.json.
        mismatch: Dictionary with 'missing' and 'extras' keys.
        logger: Logger instance.
    """
    if not os.path.isfile(summary_file):
        logger.warning(f"summary.json not found: {summary_file}")
        return

    try:
        with open(summary_file, 'r', encoding='utf-8') as jf:
            designs_summary = json.load(jf)

        for design_name in designs_summary:
            designs_summary[design_name]['Status'] = 'False'
            designs_summary[design_name]['Failure_Reason'] = (
                f"License mismatch - Missing={mismatch['missing']}, Extras={mismatch['extras']}"
            )

        tmp_file = summary_file + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as jf:
            json.dump(designs_summary, jf, indent=2)
        
        os.replace(tmp_file, summary_file)
        logger.info("Annotated summary.json with license mismatch details.")

    except Exception as e:
        logger.error(f"Unable to update summary.json: {e}")


def pos_simulation(args: Dict[str, Any]) -> None:
    """
    Post-simulation housekeeping step.

    Actions:
      - Collect license log if present (FlexNet).
      - Copy to Results directory.
      - Compare against gold licenses (if log exists).
      - Annotate summary.json on mismatch.

    Notes:
      - Under Web Licensing, FlexNet logs may be absent (this is normal).
      - Test does NOT fail if license log is missing.

    Args:
        args: Configuration dictionary (must contain 'dst_dir').
    """
    log_file = os.path.join(args['dst_dir'], 'pos_simulation.log')
    logger = helper_functions.get_logger(log_file, logging.INFO)

    time.sleep(args.get('post_wait_seconds', 10))

    # Get license log path
    machine_name = socket.gethostname()
    lic_log_dir = os.path.join(tempfile.gettempdir(), '.ansys')
    lic_log = f'ansyscl.{machine_name}.log'
    lic_log_file = os.path.join(lic_log_dir, lic_log)

    results_folder = os.path.join(args['dst_dir'], "Results")
    os.makedirs(results_folder, exist_ok=True)

    # Copy license log if present
    if os.path.isfile(lic_log_file):
        try:
            shutil.copy(lic_log_file, results_folder)
            logger.info("Copied license log file to Results folder")
        except Exception as e:
            logger.warning(f"Could not copy license log: {e}")
    else:
        logger.info(f"License log not found (expected under Web Licensing)")
        return

    # Analyze and compare licenses
    gold_licenses = args.get('gold_licenses', [
        'simplorer_gui', 'simplorer_desktop', 'simplorer_sim', 'simplorer_twin_models'
    ])

    test_licenses = LicenseLogAnalyzer.read_license_log(lic_log_file, logger)

    if not test_licenses:
        logger.info("No FlexNet CHECKOUT entries found (normal with Web Licensing).")
        return

    mismatch = LicenseLogAnalyzer.compare_licenses(gold_licenses, test_licenses, logger)

    if mismatch:
        summary_file = os.path.join(args['dst_dir'], 'summary.json')
        _annotate_summary_with_license_mismatch(summary_file, mismatch, logger)


# ==============================================================================================
# SECTION 7: ENTRY POINT
# ==============================================================================================

if __name__ == '__main__':
    """
    Script entry point (runs under AEDT/Simplorer host).
    
    Expected globals provided by host:
        - ScriptArgument: Dictionary of configuration arguments.
        - oDesktop: Ansys AEDT desktop object.
    """
    args = ScriptArgument  # noqa: F821
    
    # Validate arguments
    try:
        ConfigValidator.validate_args(args)
    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    # Pre-simulation setup
    try:
        pre_simulation(args)
    except Exception as e:
        print(f"Pre-simulation failed: {e}")
        sys.exit(1)

    # Main simulation and comparison
    try:
        simulate_and_compare(args, oDesktop)  # noqa: F821
    except Exception as e:
        print(f"Simulation failed: {e}")
        sys.exit(1)

    # Post-simulation housekeeping
    try:
        pos_simulation(args)
    except Exception as e:
        print(f"Post-simulation failed: {e}")
        # Note: Don't exit here; post-sim issues shouldn't fail entire workflow