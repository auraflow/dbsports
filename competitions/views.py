from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Stage, Result
from .forms import ResultForm
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed
from django.db.models import Sum
from .models import Competition, ResultLog, AuditLog, Participant, Role
from .models import Team, TeamMember
from django.contrib.auth import logout
from .forms import CompetitionForm, ParticipantForm, StageForm, TeamForm, TeamMemberForm
from django.views.decorators.http import require_POST
from functools import wraps
from .services import calculate_stage_standings
import csv


# Универсальный декоратор для проверки ролей
def role_required(allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Суперюзер имеет доступ ко всему
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            # ЗАЩИТА ОТ ОШИБКИ 500: проверяем, есть ли вообще роль у пользователя
            if not request.user.role:
                return HttpResponseForbidden("У вас нет назначенной роли в системе.")
            
            # Проверяем, входит ли роль пользователя в список разрешенных
            if request.user.role.role_name not in allowed_roles:
                return HttpResponseForbidden("У вас нет прав для доступа к этой странице.")
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

# Готовые декораторы для конкретных ролей (используем Choices из обновленных моделей)
organizer_required = role_required([Role.RoleNames.ORGANIZER])
chief_judge_required = role_required([Role.RoleNames.ORGANIZER, Role.RoleNames.CHIEF_JUDGE])

@login_required
def dashboard(request):
    # Главное меню системы
    return render(request, 'competitions/dashboard.html')

@login_required
def stage_list(request):
    # Экран выбора активного этапа соревнования
    stages = Stage.objects.filter(competition__is_archived=False).select_related('competition').order_by('competition__title', 'id')
    return render(request, 'competitions/stage_list.html', {'stages': stages})

@login_required
def enter_result(request, stage_id):
    # Подпроцесс проведения этапа соревнования с оперативным вводом результатов
    stage = get_object_or_404(Stage, pk=stage_id)
    
    if request.method == 'POST':
        form = ResultForm(request.POST)
        if form.is_valid():
            result = form.save(commit=False)

            # ЗАЩИТА: Проверяем, нет ли уже результата у этого участника на этом этапе
            if Result.objects.filter(participant=result.participant, stage=stage).exists():
                form.add_error('participant', 'Ошибка: Результат для этого участника уже был зафиксирован ранее!')
            else:
                result.stage = stage
                result.judge = request.user
                result.save()          

            AuditLog.objects.create(
                user=request.user,
                competition=result.participant.competition,
                action="Ввод результата",
                details=f"Судья зафиксировал результат для {result.participant.full_name} на этапе «{result.stage.name}»: {result.value} (штраф: {result.penalty_value})."
            )

            return redirect('enter_result', stage_id=stage.id)
    else:
        form = ResultForm()
        form.fields['participant'].queryset = stage.competition.participants.all()
        
    recent_results = Result.objects.filter(stage=stage).order_by('-created_at')[:5]
    
    return render(request, 'competitions/enter_result.html', {
        'stage': stage,
        'form': form,
        'recent_results': recent_results
    })

@login_required
def stage_leaderboard(request, stage_id):
    # Экран итогового рейтинга (турнирная таблица этапа)
    stage = get_object_or_404(Stage, pk=stage_id)
    standings = calculate_stage_standings(stage.id)
    
    return render(request, 'competitions/leaderboard.html', {
        'stage': stage,
        'standings': standings
    })

# ==========================================
# БЛОК ГЛАВНОГО СУДЬИ (ВЕРИФИКАЦИЯ)
# ==========================================

@login_required
@chief_judge_required
@require_POST
def verify_results_backend(request, stage_id):
    """
    Бэкенд-обработчик действий Главного судьи (срабатывает при нажатии кнопок верификации)
    """
    stage = get_object_or_404(Stage, pk=stage_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        result_id = request.POST.get('result_id')
        res = get_object_or_404(Result, pk=result_id)

        if action == 'verify':
            res.is_verified = True
            res.save()

            # --- ДОБАВИТЬ ЛОГ ---
            AuditLog.objects.create(
                user=request.user,
                competition=res.participant.competition,
                action="Верификация результата",
                details=f"Главный судья подтвердил результат участника {res.participant.full_name} на этапе «{res.stage.name}» без изменений."
            )

        elif action == 'edit_penalty':
            new_penalty = request.POST.get('new_penalty')
            reason = request.POST.get('reason', 'Корректировка Главным судьей')
            
            # Фиксация в журнале аудита (Таблица 17 диплома)
            ResultLog.objects.create(
                result=res,
                changed_by=request.user,
                old_value=res.penalty_value,
                new_value=new_penalty,
                comment=reason
            )
            res.penalty_value = new_penalty
            res.is_verified = True # Автоматически подтверждаем при исправлении
            res.save()

            # --- ДОБАВЛЕНО: Запись в общий Журнал аудита ---
            AuditLog.objects.create(
                user=request.user,
                competition=res.participant.competition,
                action="Удаление результата",
                details=f"Главный судья удалил результат участника {res.participant.full_name} на этапе «{res.stage.name}»."
            )

        # Теперь перенаправляем обратно в панель верификации этапа
        return redirect('stage_verify_panel', stage_id=stage.id)


@login_required
@chief_judge_required
def chief_stage_list(request):
    """
    Экран Главного судьи: список всех этапов для контроля данных
    """
    user_role = request.user.role.role_name if request.user.role else ''
    if user_role not in ['Главный судья', 'Организатор'] and not request.user.is_superuser:
        return redirect('dashboard')
        
    stages = Stage.objects.filter(competition__is_archived=False).select_related('competition').order_by('competition__title', 'id')
    return render(request, 'competitions/chief_stage_list.html', {'stages': stages})


@login_required
@chief_judge_required
def stage_verify_panel(request, stage_id):
    """
    Интерактивная панель верификации результатов конкретного этапа
    """
    user_role = request.user.role.role_name if request.user.role else ''
    if user_role not in ['Главный судья', 'Организатор'] and not request.user.is_superuser:
        return redirect('dashboard')
        
    stage = get_object_or_404(Stage, pk=stage_id)
    # Загружаем результаты, сначала показываем невыверенные (is_verified=False)
    results = Result.objects.filter(stage=stage).select_related('participant', 'judge').order_by('is_verified', '-created_at')
    
    return render(request, 'competitions/stage_verify.html', {
        'stage': stage,
        'results': results
    })

# ==========================================
# БЛОК ОРГАНИЗАТОРА (ОТЧЕТНОСТЬ И ВЫГРУЗКА)
# ==========================================

@login_required
@organizer_required
def competition_summary(request, comp_id):
    """
    Сводный отчет по соревнованию (Веб-дашборд).
    """
    competition = get_object_or_404(Competition, pk=comp_id)
    
            
    from django.db.models import Sum
    
    individual_summary = []
    team_summary = []
    
    # === 1. РАСЧЕТ ЛИЧНОГО ЗАЧЕТА ===
    if competition.has_individual or competition.has_team:
        participants = competition.participants.all()
        for p in participants:
            verified_results = Result.objects.filter(participant=p, stage__competition=competition, is_verified=True)
            
            t_time = verified_results.aggregate(Sum('value'))['value__sum'] or 0
            t_pen = verified_results.aggregate(Sum('penalty_value'))['penalty_value__sum'] or 0
            
            # Флаг: проверяем, выступал ли человек вообще
            has_results = verified_results.exists()
            
            # Добавляем в таблицу АБСОЛЮТНО ВСЕХ участников
            individual_summary.append({
                'participant': p,
                'total_penalty': t_pen,
                'final_score': float(t_time) + float(t_pen),
                'has_results': has_results
            })
                
        # УМНАЯ СОРТИРОВКА ЛИЧНОГО ЗАЧЕТА:
        # Условие `not x['has_results']` вернет True для пустых спортсменов -> они улетят в самый конец таблицы.
        # Остальные отсортируются по финальному результату (по возрастанию).
        individual_summary.sort(key=lambda x: (not x['has_results'], x['final_score']))

    # === 2. РАСЧЕТ КОМАНДНОГО ЗАЧЕТА ===
    if competition.has_team:
        teams = competition.teams.prefetch_related('members__participant').all()
        for team in teams:
            team_score = 0
            members_count = 0
            for member in team.members.all():
                p = member.participant
                p_result = next((item for item in individual_summary if item['participant'] == p), None)
                
                # Добавляем баллы отряду, ТОЛЬКО если у спортсмена есть реальные результаты
                if p_result and p_result['has_results']:
                    team_score += p_result['final_score']
                    members_count += 1
                    
            team_summary.append({
                'team': team.team_name,
                'members_count': members_count,
                'team_score': team_score
            })
            
        # УМНАЯ СОРТИРОВКА ОТРЯДОВ:
        team_summary.sort(key=lambda x: (x['members_count'] == 0, x['team_score'] == 0, x['team_score']))

    return render(request, 'competitions/summary.html', {
        'competition': competition,
        'individual_summary': individual_summary,
        'team_summary': team_summary
    })

@login_required
@organizer_required
def export_csv_report(request, comp_id):
    """
    Бэкенд-генерация файла отчета (CSV - открывается в Excel).
    Выполняет требование ФТ-07 из диплома.
    """
    competition = get_object_or_404(Competition, pk=comp_id)
    
    # Создаем HTTP-ответ с типом файла CSV
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig') # utf-8-sig для русского языка в Excel
    response['Content-Disposition'] = f'attachment; filename="Report_{competition.id}.csv"'
    
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Соревнование:', competition.title, 'Дата:', competition.start_date])
    writer.writerow(['']) # Пустая строка
    writer.writerow(['Место', 'Стартовый номер', 'ФИО Участника', 'Основной показатель', 'Сумма штрафов', 'Итоговый результат'])
    
    # Заново собираем сводку (в идеале вынести этот расчет в services.py, чтобы не дублировать код)
    participants = competition.participants.all()
    summary = []
    for p in participants:
        t_val = Result.objects.filter(participant=p, stage__competition=competition, is_verified=True).aggregate(Sum('value'))['value__sum'] or 0
        t_pen = Result.objects.filter(participant=p, stage__competition=competition, is_verified=True).aggregate(Sum('penalty_value'))['penalty_value__sum'] or 0
        summary.append({'name': p.full_name, 'bib': p.bib_number, 'val': t_val, 'pen': t_pen, 'final': float(t_val) + float(t_pen)})
        
    summary.sort(key=lambda x: x['final'])
    
    for index, row in enumerate(summary):
        writer.writerow([index + 1, row['bib'], row['name'], row['val'], row['pen'], row['final']])
        
    return response

@login_required
def logout_view(request):
    logout(request)
    return redirect('login') # Перенаправляем на наш новый маршрут входа

@login_required
@organizer_required
def organizer_competitions(request):
    # Страница со списком всех соревнований для Организатора
        
    competitions = Competition.objects.filter(is_archived=False).order_by('-start_date')
    return render(request, 'competitions/organizer_list.html', {'competitions': competitions})

@login_required
@organizer_required
def create_competition(request):
    # Форма создания нового соревнования (ФТ-01)
            
    if request.method == 'POST':
        form = CompetitionForm(request.POST)
        if form.is_valid():
            competition = form.save(commit=False)
            competition.created_by = request.user  # Привязываем создателя
            competition.save()

            # --- ДОБАВИТЬ ЛОГ ---
            AuditLog.objects.create(
                user=request.user,
                competition=competition,
                action="Создание соревнования",
                details=f"Организатор создал новое соревнование: «{competition.title}»."
            )

            return redirect('organizer_competitions')
    else:
        form = CompetitionForm()
    return render(request, 'competitions/create_competition.html', {'form': form})

@login_required
@organizer_required
def manage_participants(request, comp_id):
    # Управление участниками конкретного соревнования (ФТ-02)
    competition = get_object_or_404(Competition, pk=comp_id)
    
            
    if request.method == 'POST':
        form = ParticipantForm(request.POST)
        if form.is_valid():
            participant = form.save(commit=False)
            participant.competition = competition # Привязываем к текущему соревнованию
            participant.save()

            # --- ДОБАВИТЬ ЛОГ ---
            AuditLog.objects.create(
                user=request.user,
                competition=competition,
                action="Добавление участника",
                details=f"Зарегистрирован участник: {participant.full_name} (Бейдж: {participant.bib_number})."
            )

            return redirect('manage_participants', comp_id=competition.id)
    else:
        form = ParticipantForm()
        
    participants = competition.participants.all().order_by('bib_number')
    return render(request, 'competitions/manage_participants.html', {
        'competition': competition,
        'form': form,
        'participants': participants
    })

@login_required
@organizer_required
def manage_stages(request, comp_id):
    """
    Управление этапами конкретного соревнования (ФТ-03)
    """
    competition = get_object_or_404(Competition, pk=comp_id)
    
            
    if request.method == 'POST':
        form = StageForm(request.POST)
        if form.is_valid():
            stage = form.save(commit=False)
            stage.competition = competition # Автоматически привязываем к текущему соревнованию
            stage.save()

            # --- ДОБАВИТЬ ЛОГ ---
            AuditLog.objects.create(
                user=request.user,
                competition=competition,
                action="Создание этапа",
                details=f"Добавлен новый этап соревнований: «{stage.name}»."
            )

            return redirect('manage_stages', comp_id=competition.id)
    else:
        form = StageForm()
        
    # Извлекаем все этапы этого соревнования вместе с типами замеров
    stages = competition.stages.all().select_related('type')
    
    return render(request, 'competitions/manage_stages.html', {
        'competition': competition,
        'form': form,
        'stages': stages
    })

@login_required
@organizer_required
def manage_teams(request, comp_id):
    """
    Управление командами соревнования (ФТ-02)
    """
    competition = get_object_or_404(Competition, pk=comp_id)
    
           
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.competition = competition
            team.save()

            # --- ДОБАВИТЬ ЛОГ ---
            AuditLog.objects.create(
                user=request.user,
                competition=competition,
                action="Создание команды",
                details=f"Создана новая команда (отряд): «{team.team_name}»."
            )

            return redirect('manage_teams', comp_id=competition.id)
    else:
        form = TeamForm()
        
    teams = competition.teams.all()
    return render(request, 'competitions/manage_teams.html', {
        'competition': competition,
        'form': form,
        'teams': teams
    })

@login_required
@organizer_required
def manage_team_members(request, team_id):
    """
    Распределение участников по командам/отрядам (Состав команд)
    """
    team = get_object_or_404(Team, pk=team_id)
    competition = team.competition
    
           
    if request.method == 'POST':
        form = TeamMemberForm(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.team = team

            # Проверяем, не состоит ли участник уже в КАКОЙ-ЛИБО команде этого соревнования
            if TeamMember.objects.filter(team__competition=competition, participant=member.participant).exists():
                form.add_error('participant', 'Ошибка: Этот участник уже числится в одной из команд данного турнира!')
            else:
                member.save()
                # --- ДОБАВИТЬ ЛОГ ---
                AuditLog.objects.create(
                    user=request.user,
                    competition=competition,
                    action="Распределение команд",
                    details=f"Участник {member.participant.full_name} добавлен в состав команды «{team.team_name}»."
                )

                return redirect('manage_team_members', team_id=team.id)


            return redirect('manage_team_members', team_id=team.id)
    else:
        form = TeamMemberForm()
        # Показываем в выпадающем списке только тех участников, которые заявлены на это соревнование
        form.fields['participant'].queryset = competition.participants.all()
        
    members = team.members.select_related('participant').all()
    return render(request, 'competitions/manage_team_members.html', {
        'team': team,
        'competition': competition,
        'form': form,
        'members': members
    })

@login_required
@organizer_required
def print_protocol(request, comp_id):
    """
    Генерация официальной печатной формы (PDF)
    Синхронизировано с логикой Дашборда + Умная сортировка нулей
    """
    competition = get_object_or_404(Competition, pk=comp_id)
    
           
    from django.db.models import Sum
    
    individual_summary = []
    team_summary = []
    
    # === 1. РАСЧЕТ ЛИЧНОГО ЗАЧЕТА ===
    if competition.has_individual or competition.has_team:
        participants = competition.participants.all()
        for p in participants:
            verified_results = Result.objects.filter(participant=p, stage__competition=competition, is_verified=True)
            
            t_time = verified_results.aggregate(Sum('value'))['value__sum'] or 0
            t_pen = verified_results.aggregate(Sum('penalty_value'))['penalty_value__sum'] or 0
            
            # Флаг: проверяем, выступал ли человек вообще
            has_results = verified_results.exists()
            
            # Добавляем в таблицу АБСОЛЮТНО ВСЕХ участников
            individual_summary.append({
                'participant': p,
                'total_penalty': t_pen,
                'final_score': float(t_time) + float(t_pen),
                'has_results': has_results
            })
                
        # УМНАЯ СОРТИРОВКА ЛИЧНОГО ЗАЧЕТА:
        # Условие `not x['has_results']` вернет True для пустых спортсменов -> они улетят в самый конец таблицы.
        # Остальные отсортируются по финальному результату (по возрастанию).
        individual_summary.sort(key=lambda x: (not x['has_results'], x['final_score']))

    # === 2. РАСЧЕТ КОМАНДНОГО ЗАЧЕТА ===
    if competition.has_team:
        teams = competition.teams.prefetch_related('members__participant').all()
        for team in teams:
            team_score = 0
            members_count = 0
            for member in team.members.all():
                p = member.participant
                p_result = next((item for item in individual_summary if item['participant'] == p), None)
                
                # Добавляем баллы отряду, ТОЛЬКО если у спортсмена есть реальные результаты
                if p_result and p_result['has_results']:
                    team_score += p_result['final_score']
                    members_count += 1
                    
            team_summary.append({
                'team': team.team_name,
                'members_count': members_count,
                'team_score': team_score
            })
            
        # УМНАЯ СОРТИРОВКА ОТРЯДОВ:
        team_summary.sort(key=lambda x: (x['members_count'] == 0, x['team_score'] == 0, x['team_score']))
    
    return render(request, 'competitions/print_protocol.html', {
        'competition': competition,
        'individual_summary': individual_summary,
        'team_summary': team_summary
    })

@login_required
@organizer_required
@require_POST
def delete_competition(request, comp_id):
    comp = get_object_or_404(Competition, pk=comp_id)

    # --- ДОБАВИТЬ ЛОГ (ДО DELETE) ---
    # Передаем competition=None, чтобы лог остался жить после удаления соревнования
    AuditLog.objects.create(
        user=request.user,
        competition=None, 
        action="Удаление соревнования",
        details=f"СИСТЕМНОЕ УДАЛЕНИЕ: Соревнование «{comp.title}» было полностью удалено из базы данных вместе со всеми связанными этапами и результатами."
    )

    comp.delete()
    return redirect('organizer_competitions')

@login_required
@organizer_required
@require_POST
def delete_stage(request, stage_id):
    stage = get_object_or_404(Stage, pk=stage_id)
    comp_id = stage.competition.id # Запоминаем ID соревнования, чтобы вернуться обратно

    # --- ДОБАВИТЬ ЛОГ (ДО DELETE) ---
    AuditLog.objects.create(
        user=request.user,
        competition=stage.competition,
        action="Удаление этапа",
        details=f"Организатор удалил этап «{stage.name}» и все его результаты."
    )

    stage.delete()
    return redirect('manage_stages', comp_id=comp_id)

@login_required
@organizer_required
@require_POST
def delete_team(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    comp_id = team.competition.id

    # --- ДОБАВИТЬ ЛОГ (ДО DELETE) ---
    AuditLog.objects.create(
        user=request.user,
        competition=team.competition,
        action="Удаление команды",
        details=f"Организатор удалил команду «{team.team_name}»."
    )

    team.delete()
    return redirect('manage_teams', comp_id=comp_id)

@login_required
@organizer_required
@require_POST
def delete_participant(request, part_id):
    participant = get_object_or_404(Participant, pk=part_id)
    comp_id = participant.competition.id

    # --- ДОБАВИТЬ ЛОГ (ДО DELETE) ---
    AuditLog.objects.create(
        user=request.user,
        competition=participant.competition,
        action="Удаление участника",
        details=f"Участник {participant.full_name} удален из списков соревнования."
    )

    participant.delete()
    return redirect('manage_participants', comp_id=comp_id)

@login_required
@organizer_required
@require_POST
def delete_team_member(request, member_id):
    member = get_object_or_404(TeamMember, pk=member_id)
    team_id = member.team.id
    
    AuditLog.objects.create(
        user=request.user,
        competition=member.team.competition,
        action="Исключение из команды",
        details=f"Участник {member.participant.full_name} исключен из команды «{member.team.team_name}»."
    )
    
    member.delete()
    return redirect('manage_team_members', team_id=team_id)

@login_required
@organizer_required
@require_POST
def toggle_archive(request, comp_id):
    """Функция для переноса соревнования в архив"""
    comp = get_object_or_404(Competition, id=comp_id)
    comp.is_archived = True
    comp.save()
    # Возвращаемся к списку соревнований организатора

    # АВТОЛОГ:
    AuditLog.objects.create(
        user=request.user,
        competition=comp,
        action="Архивация",
        details=f"Соревнование «{comp.title}» успешно перенесено в архив и заморожено."
    )

    return redirect('organizer_competitions')

@login_required
@organizer_required
def archive_list(request):
    """Страница модуля отчетности и архива"""
    # Забираем только те, что в архиве
    # --- ДОБАВЛЕНА ЗАЩИТА ---
    
    archived_comps = Competition.objects.filter(is_archived=True).order_by('-start_date')
    return render(request, 'competitions/archive_list.html', {'competitions': archived_comps})

@login_required
@organizer_required
def export_excel(request, comp_id):
    """Генерация CSV-файла (читается в Excel) с результатами"""
    # --- ДОБАВЛЕНА ЗАЩИТА ---
    
    comp = get_object_or_404(Competition, id=comp_id)
    
    # Настраиваем HTTP-ответ так, чтобы браузер скачал это как файл
    response = HttpResponse(content_type='text/csv')
    # Добавляем BOM-маркер (\ufeff), чтобы русский язык в Excel отображался идеально
    response.write('\ufeff'.encode('utf8'))
    response['Content-Disposition'] = f'attachment; filename="Export_{comp.id}_Results.csv"'
    
    # Используем разделитель 'точка с запятой' (стандарт для русского Excel)
    writer = csv.writer(response, delimiter=';')
    
    # Пишем заголовки столбцов
    writer.writerow(['ФИО Участника', 'Номер (Бейдж)', 'Название этапа', 'Результат', 'Штраф'])
    
    # Получаем все верифицированные результаты этого соревнования
    results = Result.objects.filter(
        participant__competition=comp,
        is_verified=True
    ).select_related('participant', 'stage')
    
    # Записываем данные построчно
    for r in results:
        writer.writerow([
            r.participant.full_name,
            r.participant.bib_number,
            r.stage.name,
            str(r.value).replace('.', ','), # Меняем точку на запятую для Excel
            str(r.penalty_value).replace('.', ',')
        ])
        
    return response

@login_required
@organizer_required
def archive_detail(request, comp_id):
    """Карточка подробного просмотра архивного соревнования"""
    # --- ДОБАВЛЕНА ЗАЩИТА ---
    
    # Убеждаемся, что получаем только соревнование со статусом "В архиве"
    comp = get_object_or_404(Competition, id=comp_id, is_archived=True)
    
    # Собираем исторические данные
    stages = Stage.objects.filter(competition=comp).order_by('id')
    teams = Team.objects.filter(competition=comp).order_by('team_name')
    participants = Participant.objects.filter(competition=comp).order_by('full_name')
    
    context = {
        'competition': comp,
        'stages': stages,
        'teams': teams,
        'participants': participants,
    }
    return render(request, 'competitions/archive_detail.html', context)

@login_required
@organizer_required
def audit_log_list(request):
    """Просмотр системного журнала действий (только для Организатора/Админа)"""
            
    # Берем последние 200 действий
    logs = AuditLog.objects.select_related('user', 'competition').all()[:200] 
    return render(request, 'competitions/audit_log.html', {'logs': logs})

@login_required
@organizer_required
def competition_panel(request, comp_id):
    """Центральный хаб (панель управления) конкретным соревнованием"""
    competition = get_object_or_404(Competition, pk=comp_id)
    
    # Собираем базовую статистику для красивого отображения
    stats = {
        'stages': competition.stages.count(),
        'participants': competition.participants.count(),
        'teams': competition.teams.count(),
    }
    
    context = {
        'competition': competition,
        'stats': stats,
    }
    return render(request, 'competitions/competition_panel.html', context)