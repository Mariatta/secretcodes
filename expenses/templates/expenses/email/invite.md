Hi{% if invitation.display_name %} {{ invitation.display_name }}{% endif %},

{{ invitation.inviter.get_full_name|default:invitation.inviter.get_username }} has invited you to join the **{{ invitation.event.name }}** event on Secret Codes Expenses.

**About this app.** Secret Codes Expenses is a small group expense tracker that Mariatta Wijaya built for friends and family — a personal project on her own site at [secretcodes.dev](https://secretcodes.dev), not a commercial service. You'll log shared expenses on a trip or gathering, see who paid for what, and settle up at the end. It's invitation-only; this email is your way in.

This app is part of Mariatta's **No Spreadsheet** movement — small purpose-built tools instead of yet another shared spreadsheet.

[Accept this invitation]({{ accept_url }})

If the link doesn't work, paste this URL into your browser:

`{{ accept_url }}`

You'll need to log in with the account associated with `{{ invitation.email }}`. If you don't have an account yet, the link above will let you set one up.

This invitation expires in {{ expiry_days }} days.

By accepting, you agree to the [Terms of Service]({{ terms_url }}) and the [Privacy Policy]({{ privacy_url }}).

— Secret Codes by Mariatta
