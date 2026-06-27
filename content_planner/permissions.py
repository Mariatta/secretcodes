"""Access control for the content planner — mirrors surveys/expenses.

App-level gating goes through ``user.has_perm`` (via
``core.permissions.has_app_access``), never a direct group-membership test.
The ``content_planner_users`` group is only the grant vehicle — it carries the
``content_planner.access_content_planner`` permission.

Per-board access is the union of (owner) ∪ (collaborator); use
``can_access_board`` for board-scoped views.

D1 is settled as **flat** for v1: any collaborator may do anything on a board
except invite others or delete the board. The ``can_*`` helpers below encode
that single rule today. Future role tiers (see ``ContentCollaborator.role``)
become rewrites of these helper bodies, not changes at the call sites.
"""

from core.permissions import has_app_access

APP_LABEL = "content_planner"
ACCESS_PERM = f"{APP_LABEL}.access_content_planner"


def is_content_user(user):
    """True if ``user`` may use the content planner creator side."""
    return user.is_authenticated and has_app_access(user, APP_LABEL)


def can_access_board(user, board):
    """True if ``user`` owns ``board`` or collaborates on it. Superusers pass."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if board.owner_id == user.id:
        return True
    return board.collaborators.filter(user=user).exists()


def can_edit_campaign(user, board):
    """Flat (v1): any board member may edit campaigns."""
    return can_access_board(user, board)


def can_edit_post(user, post):
    """Flat (v1): any board member may edit posts."""
    return can_access_board(user, post.campaign.board)


def can_publish_post(user, post):
    """Flat (v1): any board member may mark a post PUBLISHED."""
    return can_access_board(user, post.campaign.board)


def can_manage_collaborators(user, board):
    """Only the board owner (or a superuser) may invite/remove collaborators."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return board.owner_id == user.id


def can_delete_board(user, board):
    """Only the board owner (or a superuser) may delete the board."""
    return can_manage_collaborators(user, board)
