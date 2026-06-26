from django.urls import path

from . import views

app_name = "content_planner"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.board_create, name="board_create"),
    path("<slug:board_slug>/", views.board_home, name="board_home"),
    path("<slug:board_slug>/schedule/", views.schedule, name="schedule"),
    path(
        "<slug:board_slug>/campaigns/",
        views.campaign_list,
        name="campaign_list",
    ),
    path(
        "<slug:board_slug>/campaigns/new/",
        views.campaign_create,
        name="campaign_create",
    ),
    path(
        "<slug:board_slug>/c/<slug:slug>/",
        views.campaign_detail,
        name="campaign_detail",
    ),
    path(
        "<slug:board_slug>/c/<slug:slug>/edit/",
        views.campaign_edit,
        name="campaign_edit",
    ),
    path(
        "<slug:board_slug>/c/<slug:slug>/p/new/",
        views.post_create,
        name="post_create",
    ),
    path(
        "<slug:board_slug>/c/<slug:slug>/p/<slug:post_slug>/",
        views.post_detail,
        name="post_detail",
    ),
    path(
        "<slug:board_slug>/c/<slug:slug>/p/<slug:post_slug>/edit/",
        views.post_edit,
        name="post_edit",
    ),
]
