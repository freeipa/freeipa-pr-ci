# FreeIPA Pull Request CI

Scripts that are used by the PR CI testing infrastructure.

## Creating vagrant template box

1. Run `create-box-template`

   This will create a vagrant box in `/tmp/image/`.

2. Perform some basic tests on the box

   **TODO**: Something we want to automate in the future.

   - Use a basic Vagrantfile that uses this box
   - Check the box can be booted up
   
      If it's stuck in `Waiting for IP address` stage, you can connect with
      `remote-viewer vnc://127.0.0.1:5900` to debug it

   - Verify your recent changes are present

3. Upload the box to [HashiCorp Atlas](https://atlas.hashicorp.com/freeipa)

   **TODO**: Another step that will be automated in the future.

   Description:

   ```
   Builds:
     - FreeIPA: <freeipa_git_sha>
     - PR CI: <pr_ci_git_sha>

   Changelog:
     - <change>
   ```

4. Create a PR against FreeIPA with the updated box

   **TODO**: This requires GitHub integration with PR CI. Omit this step for
   now and just use the box in Vagrantfiles.

   This will run the PR CI tests with the new box. Once all the tests pass and
   the PR is merged, the PR CI will use the new template.
