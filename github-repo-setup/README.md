# Setting up your version-controlled repo

This is an absolute essential. Submission of all work and evidence of your achievement will be through a ‘portfolio submission’ via GitHub instance (this will be private to you, so you must invite ‘@is-professor’ as a collaborator).

To set this up, go to ```https://github.com``` and log in to create an account if you don’t already have one.

- Read about [the basics of version control](https://about.gitlab.com/topics/version-control/)
- You may find [these step-by-step tutorials](https://www.w3schools.com/git/default.asp?remote=github) also useful if you haven’t used git before

Essentially, the idea is that you ‘check out’ (normally) the latest version of a project from the server to your local machine. Work on the content (mainly **markdown** text files ending in ‘```.md```’ in this case). **Add the new files** and **commit** your changes (with a helpful message explaining what you’ve done is a key thing). Then **push** a copy of your repo to the server with ‘```git push```’.

The great thing is, there’s a backup version of not just your work, but each important step leading up to where you are now. *This will be important for the overall assessment of your work*.

It’ll take a while to ‘get comfy’ with how this works in practice, although this is important general learning (to use git from the terminal). You might find it easier to use [the built-in git client in VS Code](https://code.visualstudio.com/docs/sourcecontrol/intro-to-git).

Repos can generally be public or private. You can invite collaborators to either. **We’d ask that all your coursework remain private to avoid unwanted code sharing**.

**Create a repo** and name it ```username-suscomp-2026-labs```. You should have a structure where there is a folder for each week’s lab that’s committed and pushed to your repo by the end of this lab. **Your repo in this case should be private**.

## A word on security

- You must use either HTTPS or SSH-based URLs for securely pushing/pulling your code. HTTPS is easier, since SSH would require that you [generate a public/private key pair](https://docs.github.com/en/authentication/connecting-to-github-with-ssh), then upload your public key to GitHub as part of your profile.
- It’s easier to [generate a ‘personal access token’](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens). You will need your token to have both read_repository and write_repository access rights.

You use a personal access token instead of a password. *You’ll want to keep this somewhere safe for future use, as once created, you can’t see it again. **Don’t share it with anyone!***

The good news is VS Code will remember your credentials for you. The git password cache will enable the password to be remembered from the terminal so you don’t have to enter your password or token every time you push/pull from the remote repo (```git config --global credential.helper cache```) from the shell.

## More version control

Ensure you understand how to use the ```SSH``` URIs (that start with ```git@``` instead of ```HTTPS```) with your key pair for cloning and pushing your repos from/to your GitHub repo.

## Acknowledgement

These instructions are made based on the materials from the Sustainable Computing course held by Adrian Friday, a Professor of Computing and Sustainability at Lancaster University.
