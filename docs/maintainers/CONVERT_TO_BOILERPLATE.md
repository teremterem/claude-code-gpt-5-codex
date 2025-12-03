# Converting to Boilerplate (aka My LiteLLM Server)

This guide is intended for the maintainers of the Claude Code GPT-5 repository to derive a "Boilerplate" version of it (aka My LiteLLM Server) upon a new version release. **If you are simply looking to use it as a boilerplate, head over to the [main-boilerplate](https://github.com/teremterem/claude-code-gpt-5/tree/main-boilerplate) branch of this repository and check out the [README](https://github.com/teremterem/claude-code-gpt-5/blob/main-boilerplate/README.md) there.**

## Prerequisites

- A GitHub [Personal Access Token (PAT)](https://github.com/settings/tokens) with the `write:packages` scope
- Docker installed on your machine
- Multi-arch `buildx` enabled in Docker (see [Docker documentation](https://docs.docker.com/build/install-buildx/))

## Steps

> **NOTE:** All the commands below are expected to be run from the root directory of the repository:

```bash
cd <repo-root-dir>
```

### Preparation

1. Backup the content of the `main` branch of the repo to a separate directory.

   **Delete the existing backup directory if it exists:**

   ```bash
   rm -r ../repo-main-backup-dir
   ```

   **Proceed with the backup:**

   ```bash
   git switch main
   git pull
   git status
   ```

   ```bash
   cp -r . ../repo-main-backup-dir
   rm -rf ../repo-main-backup-dir/.git
   rm -rf ../repo-main-backup-dir/.venv
   rm ../repo-main-backup-dir/.env
   rm ../repo-main-backup-dir/librechat/.env
   ```

2. Backup the content of the `main-boilerplate` branch of the repo to a separate directory.

    **Delete the existing backup directory if it exists:**

   ```bash
   rm -r ../repo-boilerplate-backup-dir
   ```

   **Proceed with the backup:**

   ```bash
   git switch main-boilerplate
   git pull
   git status
   ```

   ```bash
   cp -r . ../repo-boilerplate-backup-dir
   rm -rf ../repo-boilerplate-backup-dir/.git
   rm -rf ../repo-boilerplate-backup-dir/.venv
   rm ../repo-boilerplate-backup-dir/.env
   rm ../repo-boilerplate-backup-dir/librechat/.env
   ```

3. Create a feature branch from `main-boilerplate`:

   ```bash
   git switch --create boilerplate-merging-branch
   ```

   ```bash
   git push --set-upstream boilerplate boilerplate-merging-branch
   ```

   > **⚠️ ATTENTION ⚠️** If `boilerplate-merging-branch` already exists, either locally or on the remote, make sure to delete both - the local branch and the remote branch - and then retry the command(s) above.

4. Merge `main` into `boilerplate-merging-branch` in the following way:

   2.1 Initiate the merge:

   ```bash
   git merge origin/main
   git status
   ```

   2.2 **IGNORE ALL THE MERGE CONFLICTS (if any).** Override everything with the files from the `main` branch and conclude the merge **(do this regardless of the presence or absence of merge conflicts):**

   ```bash
   cp -r ../repo-main-backup-dir/* .
   cp -r ../repo-main-backup-dir/.* .
   git add --all
   git status
   ```

   ```bash
   git commit -m 'Merge remote-tracking branch '\''superorigin/main'\'' into boilerplate-merging-branch'
   git push
   git status
   ```

5. **Create a feature branch from the feature branch:**

   ```bash
   git switch --create boilerplate-MANUAL-merging-branch
   ```

   ```bash
   git push --set-upstream boilerplate boilerplate-MANUAL-merging-branch
   ```

   > **⚠️ ATTENTION ⚠️** If `boilerplate-MANUAL-merging-branch` already exists, either locally or on the remote, make sure to delete both - the local branch and the remote branch - and then retry the command(s) above.

### Delete irrelevant files

6. Delete the following files and folders, as they are not supposed to be part of the boilerplate:

   ```bash
   rm -rf claude_code_proxy/
   rm -rf docs/maintainers/
   rm images/claude-code-*
   rm deploy-docker.sh
   rm kill-docker.sh
   rm run-docker.sh

   git add --all
   git status
   ```

   ```bash
   git commit -m "Delete irrelevant files"
   git push
   git status
   ```

### Swap the README

7. Override `README.md` with `README_BOILERPLATE.md`:

   ```bash
   mv README_BOILERPLATE.md README.md

   git add --all
   git status
   ```

   ```bash
   git commit -m "Override README with README_BOILERPLATE.md"
   git push
   git status
   ```

8. Edit the new `README.md` to restore a **NOTE** clause at the top of it:

   ```bash
   vim README.md
   ```

   **Replace the existing ATTENTION clause at the top with the following text:**

   ```markdown
   > **NOTE:** Check out our [claude-code-gpt-5-codex](https://github.com/teremterem/claude-code-gpt-5-codex) repository, if you would like to use Anthropic's `Claude Code CLI` with OpenAI models like `GPT-5 Codex`, `GPT-5.1`, and others.
   ```

   ```bash
   git add --all
   git status
   ```

   ```bash
   git commit -m "Restore note about checking out Claude Code CLI Proxy repository"
   git push
   git status
   ```

### Restore boilerplate-specific versions of certain files

9. Copy the following files over from the `main-boilerplate` branch:

   ```bash
   cp ../repo-boilerplate-backup-dir/docs/DOCKER_TIPS.md docs/
   cp ../repo-boilerplate-backup-dir/.env.template .
   cp ../repo-boilerplate-backup-dir/config.yml .
   cp ../repo-boilerplate-backup-dir/docker-compose.dev.yml .
   cp ../repo-boilerplate-backup-dir/docker-compose.yml .
   cp ../repo-boilerplate-backup-dir/uv-run.sh .

   git add --all
   git status
   ```

   ```bash
   git commit -m "Restore boilerplate-specific versions of certain files"
   git push
   git status
   ```

### Correct certain files manually

10. REMOVE the following entries from `config.yaml`:

    ```bash
    vim config.yaml
    ```

    ```yaml
    # litellm_settings: custom_provider_map:
    - provider: claude_code_router
      custom_handler: claude_code_proxy.claude_code_router.claude_code_router
    ```

    ```yaml
    # model_list:
    - model_name: "*"
      litellm_params:
        model: "claude_code_router/*"
        drop_params: true  # Automatically drop unsupported parameters
    ```

11. REMOVE the following lines from `Dockerfile`:

    ```bash
    vim Dockerfile
    ```

    ```dockerfile
    LABEL org.opencontainers.image.source=https://github.com/teremterem/claude-code-gpt-5 \
          org.opencontainers.image.description="Connect Claude Code CLI to GPT-5" \
          org.opencontainers.image.licenses=MIT
    ```

12. Update the `name`, `version` and `description` fields in `pyproject.toml` in the following way:

    ```bash
    vim pyproject.toml
    ```

    ```toml
    # ...
    name = "my-litellm-server"
    version = "X.X.X.X"  # Replace with numbers
    description = "LiteLLM server boilerplate"
    # ...
    ```

    As you can see, the `version` number has four components. **The last component is the version of the boilerplate itself within the global claude code proxy release.**

13. Regenerate `uv.lock` file:

    ```bash
    uv lock --no-upgrade
    ```

    > **NOTE:** You are not meant to upgrade any packages with the `--upgrade` flag while converting to boilerplate - that is meant to be done earlier, as part of the `main` branch development.

14. Commit and push:

    ```bash
    git add --all
    git status
    ```

    ```bash
    git commit -m "Update Dockerfile, config.yaml, pyproject.toml and uv.lock"
    git push
    git status
    ```

### Merge the rest of the files the usual way

The remaining files and folders should be merged the usual way. Files and folders like:

- `common/`
- `librechat/`
- `yoda_example/`
- the rest of the files in the root directory
- etc.

So, in order to conclude the conversion, do the following.

15. Create a GitHub Pull Request of `boilerplate-MANUAL-merging-branch` into `boilerplate-merging-branch`:

    ```bash
    gh pr create \
       --base boilerplate-merging-branch \
       --head boilerplate-MANUAL-merging-branch \
       --title 'Merge '\`'boilerplate-MANUAL-merging-branch'\`' into '\`'boilerplate-merging-branch'\` \
       --body ""
    ```

    (Or do this through the GitHub web interface, if you prefer.)

16. **Thoroughly review the diff in this PR and make changes in `boilerplate-MANUAL-merging-branch` if needed.**

    Things to look for:

    - Check the deleted `docs/maintainers/RELEASE.md` against relevant sections in the new `README.md` (the content of which came from `README_BOILERPLATE.md`) to see if there isn't anything useful that could be incorporated into those sections of the README.md.
    - Look through EVERYTHING: deleted files, modified files, added files; in case of modified files, look through both - the old and the new versions of the changed lines.

    **The goal is to see if there isn't anything that needs to be incorporated from the non-boilerplate version into the boilerplate version MANUALLY.**

### Final steps

17. Take a moment to think if nothing was forgotten (e.g. something new was introduced, which this guide doesn't cover yet).

18. SQUASH and merge `boilerplate-MANUAL-merging-branch` into `boilerplate-merging-branch` using the Pull Request that you created:

    ```bash
    gh pr merge --squash --delete-branch
    ```

19. Create a GitHub Pull Request of `boilerplate-merging-branch` into `main-boilerplate`:

    ```bash
    gh pr create \
       --base main-boilerplate \
       --head boilerplate-merging-branch \
       --title 'Merge '\`'boilerplate-merging-branch'\`' into '\`'main-boilerplate'\` \
       --body ""
    ```

    (Or do this through the GitHub web interface, if you prefer.)

20. **REVIEW the PR for the final `boilerplate-merging-branch` as well.**

21. **TEST `boilerplate-merging-branch`.**

22. Merge `boilerplate-merging-branch` into `main-boilerplate` using the Pull Request that you created. **DO NOT SQUASH, DO A MERGE COMMIT INSTEAD!** We want `main-boilerplate` to be marked as in-sync with the `main` branch:

    ```bash
    gh pr merge --merge --delete-branch
    ```

23. **TEST `main-boilerplate` after the final merge.**

24. Tag the new version:

    ```bash
    git tag -a <X.X.X.X>  # Replace <X.X.X.X>
    ```

    ```bash
    git push --tags
    git status
    ```

25. Go to the GitHub Releases page and create a new release:

    - **Title:** `X.X.X.X (boilerplate release)`
    - **Description:** \<release notes\>
    - **Discussion:** create a new discussion
    - **Mark as latest:** FALSE

26. Login to GHCR:

    > **NOTE:** At this point you need a GitHub [Personal Access Token (PAT)](https://github.com/settings/tokens) with the `write:packages` scope.

    ```bash
    # Replace <GITHUB_PAT> and <GITHUB_USERNAME>
    echo <GITHUB_PAT> | docker login ghcr.io -u <GITHUB_USERNAME> --password-stdin
    ```

27. Build the `litellm-server-yoda` image and push it to GHCR:

    ```bash
    docker buildx build \
      --platform linux/amd64,linux/arm64 \
      -t ghcr.io/teremterem/litellm-server-yoda:<X.X.X.X> \  # Replace <X.X.X.X>
      -t ghcr.io/teremterem/litellm-server-yoda:<X.X.X> \  # Replace <X.X.X>
      -t ghcr.io/teremterem/litellm-server-yoda:latest \
      --push .
    ```

28. Build the `librechat-yoda` image and push it to GHCR:

    ```bash
    docker buildx build \
      --platform linux/amd64,linux/arm64 \
      -t ghcr.io/teremterem/librechat-yoda:<X.X.X.X> \  # Replace <X.X.X.X>
      -t ghcr.io/teremterem/librechat-yoda:<X.X.X> \  # Replace <X.X.X>
      -t ghcr.io/teremterem/librechat-yoda:latest \
      --push \
      librechat/
    ```

29. **NAVIGATE to the Packages tab in GitHub and visually inspect that both images were published with proper version tags.**

30. Modify `librechat/docker-compose.override.yml` according to instruction in its own comments so it uses the published `litellm-server-yoda` and `librechat-yoda` images instead of your local source files:

    ```bash
    vim librechat/docker-compose.override.yml
    git diff
    ```

31. **TEST THE PUBLISHED IMAGES:**

    ```bash
    ./librechat/run-docker-compose.sh --pull always
    ```

33. Get rid of the changes from the previous step:

    ```bash
    git checkout librechat/docker-compose.override.yml
    git status
    ```

---

That's it! You have converted the Claude Code GPT-5 Proxy to a Boilerplate version (aka My LiteLLM Server) and published the Docker images to GHCR. Now you can go back to the [RELEASE.md](RELEASE.md) guide to release the new version of the Claude Code GPT-5 Proxy itself.
