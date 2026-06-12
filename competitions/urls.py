from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Авторизация
    path('login/', auth_views.LoginView.as_view(template_name='competitions/login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Основные интерфейсы
    path('', views.dashboard, name='dashboard'),
    path('stages/', views.stage_list, name='stage_list'),
    path('stage/<int:stage_id>/enter/', views.enter_result, name='enter_result'),
    path('stage/<int:stage_id>/leaderboard/', views.stage_leaderboard, name='stage_leaderboard'),
    
    # Бэкенд-маршруты
    path('stage/<int:stage_id>/verify/', views.verify_results_backend, name='verify_results_backend'),
    path('competition/<int:comp_id>/summary/', views.competition_summary, name='competition_summary'),
    path('competition/<int:comp_id>/export/', views.export_csv_report, name='export_csv_report'),
    path('competition/<int:comp_id>/print/', views.print_protocol, name='print_protocol'),

    # Интерфейсы Организатора
    path('organizer/competitions/', views.organizer_competitions, name='organizer_competitions'),
    path('organizer/competitions/create/', views.create_competition, name='create_competition'),
    path('organizer/competitions/<int:comp_id>/participants/', views.manage_participants, name='manage_participants'),

    # Маршруты верификации для Главного судьи
    path('chief/stages/', views.chief_stage_list, name='chief_stage_list'),
    path('chief/stage/<int:stage_id>/verify/', views.stage_verify_panel, name='stage_verify_panel'),
    
    path('organizer/competitions/<int:comp_id>/stages/', views.manage_stages, name='manage_stages'),

    path('organizer/competitions/<int:comp_id>/teams/', views.manage_teams, name='manage_teams'),
    path('organizer/teams/<int:team_id>/members/', views.manage_team_members, name='manage_team_members'),

    # Функции удаления (Управление структурой)
    path('competition/<int:comp_id>/delete/', views.delete_competition, name='delete_competition'),
    path('stage/<int:stage_id>/delete/', views.delete_stage, name='delete_stage'),
    path('team/<int:team_id>/delete/', views.delete_team, name='delete_team'),
    path('participant/<int:part_id>/delete/', views.delete_participant, name='delete_participant'),

    path('archive/', views.archive_list, name='archive_list'),
    path('archive/<int:comp_id>/toggle/', views.toggle_archive, name='toggle_archive'),
    path('export/<int:comp_id>/csv/', views.export_excel, name='export_excel'),

    path('archive/<int:comp_id>/detail/', views.archive_detail, name='archive_detail'),

    path('audit-log/', views.audit_log_list, name='audit_log_list'),

    path('team-member/<int:member_id>/delete/', views.delete_team_member, name='delete_team_member'),

    path('competition/<int:comp_id>/panel/', views.competition_panel, name='competition_panel'),
]