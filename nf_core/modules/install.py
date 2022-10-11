import logging
import os

import questionary

import nf_core.modules.module_utils
import nf_core.utils
from nf_core.modules.modules_json import ModulesJson

from .modules_command import ModuleCommand
from .modules_repo import NF_CORE_MODULES_NAME

log = logging.getLogger(__name__)


class ModuleInstall(ModuleCommand):
    def __init__(
        self,
        pipeline_dir,
        force=False,
        prompt=False,
        sha=None,
        remote_url=None,
        branch=None,
        no_pull=False,
    ):
        super().__init__(pipeline_dir, remote_url, branch, no_pull)
        self.force = force
        self.prompt = prompt
        self.sha = sha

    def install(self, module, silent=False):
        if self.repo_type == "modules":
            log.error("You cannot install a module in a clone of nf-core/modules")
            return False
        # Check whether pipelines is valid
        if not self.has_valid_directory():
            return False

        # Check modules directory structure
        self.check_modules_structure()

        # Verify that 'modules.json' is consistent with the installed modules
        modules_json = ModulesJson(self.dir)
        modules_json.check_up_to_date()

        if self.prompt and self.sha is not None:
            log.error("Cannot use '--sha' and '--prompt' at the same time!")
            return False

        # Verify that the provided SHA exists in the repo
        if self.sha:
            if not self.modules_repo.sha_exists_on_branch(self.sha):
                log.error(f"Commit SHA '{self.sha}' doesn't exist in '{self.modules_repo.remote_url}'")
                return False

        if module is None:
            module = questionary.autocomplete(
                "Tool name:",
                choices=self.modules_repo.get_avail_modules(),
                style=nf_core.utils.nfcore_question_style,
            ).unsafe_ask()

        # Check that the supplied name is an available module
        if module and module not in self.modules_repo.get_avail_modules():
            log.error(f"Module '{module}' not found in list of available modules.")
            log.info("Use the command 'nf-core modules list' to view available software")
            return False

        if not self.modules_repo.module_exists(module):
            warn_msg = (
                f"Module '{module}' not found in remote '{self.modules_repo.remote_url}' ({self.modules_repo.branch})"
            )
            log.warning(warn_msg)
            return False

        current_version = modules_json.get_module_version(
            module, self.modules_repo.remote_url, self.modules_repo.repo_path
        )

        # Set the install folder based on the repository name
        install_folder = os.path.join(self.dir, "modules", self.modules_repo.repo_path)

        # Compute the module directory
        module_dir = os.path.join(install_folder, module)

        # Check that the module is not already installed
        if (current_version is not None and os.path.exists(module_dir)) and not self.force:
            log.info("Module is already installed.")

            self.force = questionary.confirm(
                f"Module {module} is already installed. Do you want to force the reinstallation?",
                style=nf_core.utils.nfcore_question_style,
                default=False,
            ).unsafe_ask()

            if not self.force:
                repo_flag = (
                    "" if self.modules_repo.repo_path == NF_CORE_MODULES_NAME else f"-g {self.modules_repo.remote_url} "
                )
                branch_flag = "" if self.modules_repo.branch == "master" else f"-b {self.modules_repo.branch} "

                log.info(
                    f"To update '{module}' run 'nf-core modules {repo_flag}{branch_flag}update {module}'. To force reinstallation use '--force'"
                )
                return False

        if self.sha:
            version = self.sha
        elif self.prompt:
            try:
                version = nf_core.modules.module_utils.prompt_module_version_sha(
                    module,
                    installed_sha=current_version,
                    modules_repo=self.modules_repo,
                )
            except SystemError as e:
                log.error(e)
                return False
        else:
            # Fetch the latest commit for the module
            version = self.modules_repo.get_latest_module_version(module)

        if self.force:
            log.info(f"Removing installed version of '{self.modules_repo.repo_path}/{module}'")
            self.clear_module_dir(module, module_dir)
            for repo_url, repo_content in modules_json.modules_json["repos"].items():
                for dir, dir_modules in repo_content["modules"].items():
                    for name, _ in dir_modules.items():
                        if name == module and dir == self.modules_repo.repo_path:
                            repo_to_remove = repo_url
                            log.info(
                                f"Removing module '{self.modules_repo.repo_path}/{module}' from repo '{repo_to_remove}' from modules.json"
                            )
                            modules_json.remove_entry(module, repo_to_remove, self.modules_repo.repo_path)
                            break

        log.info(f"{'Rei' if self.force else 'I'}nstalling '{module}'")
        log.debug(f"Installing module '{module}' at modules hash {version} from {self.modules_repo.remote_url}")

        # Download module files
        if not self.install_module_files(module, version, self.modules_repo, install_folder):
            return False

        if not silent:
            # Print include statement
            module_name = "_".join(module.upper().split("/"))
            log.info(
                f"Include statement: include {{ {module_name} }} from '.{os.path.join(install_folder, module)}/main'"
            )

        # Update module.json with newly installed module
        modules_json.load()
        modules_json.update(self.modules_repo, module, version)
        return True
