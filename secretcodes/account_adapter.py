from allauth.account.adapter import DefaultAccountAdapter

class SecretCodesAccountAdapter(DefaultAccountAdapter):

    def is_open_for_signup(self, request):
        """
        Not open for signup.
        """
        return False