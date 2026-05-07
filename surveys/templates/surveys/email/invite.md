Hi,

{{ invitation.inviter.get_full_name|default:invitation.inviter.get_username }} has invited you to collaborate on the **{{ invitation.survey.title }}** survey on Secret Codes Surveys.

**About this app.** Secret Codes Surveys is a small anonymous-feedback tool that Mariatta Wijaya built for events and side-projects — a personal project on her own site at [secretcodes.dev](https://secretcodes.dev), not a commercial service. As a collaborator you'll be able to edit the survey's questions, read responses, group them into themes, and write action items. You won't be able to invite further collaborators or create new surveys of your own.

[Accept this invitation]({{ accept_url }})

If the link doesn't work, paste this URL into your browser:

`{{ accept_url }}`

You'll need to log in with the account associated with `{{ invitation.email }}`. If you don't have an account yet, the link above will let you set one up.

This invitation expires in {{ expiry_days }} days.

By accepting, you agree to the [Terms of Service]({{ terms_url }}) and the [Privacy Policy]({{ privacy_url }}).

— Secret Codes by Mariatta
