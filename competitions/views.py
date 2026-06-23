import csv
import openpyxl
from functools import wraps
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.http import HttpResponse, JsonResponse
from django.db.models import ProtectedError, Q 
from django.contrib import messages
from django.urls import reverse
from django.db import IntegrityError

from .models import (
    Competition, Stage, Result, Team, TeamMember, 
    Participant, ResultLog, AuditLog, Role
)
from .forms import (
    CompetitionForm, ParticipantForm, StageForm, 
    TeamForm, TeamMemberForm, ResultForm
)
from .services import calculate_stage_standings


# ==========================================
# 1. СИСТЕМА БЕЗОПАСНОСТИ И ДЕКОРАТОРЫ
# ==========================================

def safe_require_POST(view_func):
    """
    Умная замена стандартному @require_POST.
    Вместо выкидывания системной ошибки 405 Method Not Allowed, 
    выдает красивый Toast и мягко возвращает пользователя назад.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.method != 'POST':
            messages.warning(request, "🛑 Недопустимый запрос. Пожалуйста, используйте кнопки интерфейса.")
            # Возвращаем пользователя туда, откуда он пришел, либо на главную панель
            return redirect(request.META.get('HTTP_REFERER', 'dashboard'))
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def role_required(allowed_roles):
    """Универсальный декоратор проверки прав доступа по ролям"""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if not request.user.role:
                # ИСПРАВЛЕНИЕ: Выводим Toast и возвращаем на главную
                messages.error(request, "🛑 Ошибка доступа: У вас нет назначенной роли в системе.")
                return redirect('dashboard')
            if request.user.role.role_name not in allowed_roles:
                # ИСПРАВЛЕНИЕ: Выводим Toast и возвращаем на главную
                messages.error(request, "🛑 Отказано в доступе: У вас нет прав для этого действия.")
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

organizer_required = role_required([Role.RoleNames.ORGANIZER])
chief_judge_required = role_required([Role.RoleNames.ORGANIZER, Role.RoleNames.CHIEF_JUDGE])

def archive_lock(view_func):
    """
    Умный декоратор: Блокирует доступ по прямым ссылкам ко всем функциям редактирования,
    если турнир находится в архиве.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        comp = None
        # Динамически определяем, с каким объектом пытается работать пользователь
        if 'comp_id' in kwargs:
            comp = get_object_or_404(Competition, pk=kwargs['comp_id'])
        elif 'stage_id' in kwargs:
            comp = get_object_or_404(Stage, pk=kwargs['stage_id']).competition
        elif 'team_id' in kwargs:
            comp = get_object_or_404(Team, pk=kwargs['team_id']).competition
        elif 'part_id' in kwargs:
            comp = get_object_or_404(Participant, pk=kwargs['part_id']).competition
        elif 'result_id' in kwargs:
            comp = get_object_or_404(Result, pk=kwargs['result_id']).stage.competition
        elif 'member_id' in kwargs:
            comp = get_object_or_404(TeamMember, pk=kwargs['member_id']).team.competition

        # Если турнир найден и он в архиве — выгоняем пользователя
        if comp and comp.is_archived:
            # ЗАЩИТА PWA: Если это фоновый AJAX запрос, возвращаем JSON с 400 статусом, чтобы телефон удалил кэш
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Турнир в архиве. Прием данных закрыт.'}, status=400)
                
            messages.error(request, f"🔒 Отказано в доступе: Соревнование «{comp.title}» находится в Архиве.")
            return redirect('dashboard')
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def owner_lock(view_func):
    """
    Декоратор безопасности (Защита от IDOR): 
    Блокирует доступ к турниру и его элементам, если пользователь не является его создателем.
    Суперпользователь имеет доступ ко всем турнирам.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Суперпользователю можно всё
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
            
        comp = None
        # Умный поиск соревнования по любому ID из URL
        if 'comp_id' in kwargs:
            comp = get_object_or_404(Competition, pk=kwargs['comp_id'])
        elif 'stage_id' in kwargs:
            comp = get_object_or_404(Stage, pk=kwargs['stage_id']).competition
        elif 'team_id' in kwargs:
            comp = get_object_or_404(Team, pk=kwargs['team_id']).competition
        elif 'part_id' in kwargs:
            comp = get_object_or_404(Participant, pk=kwargs['part_id']).competition
        elif 'result_id' in kwargs:
            comp = get_object_or_404(Result, pk=kwargs['result_id']).stage.competition
        elif 'member_id' in kwargs:
            comp = get_object_or_404(TeamMember, pk=kwargs['member_id']).team.competition

        # Если соревнование найдено, проверяем права доступа
        if comp:
            is_creator = (comp.created_by == request.user)
            is_assigned_chief = (comp.chief_judge == request.user)
            
            # Доступ разрешен создателю турнира ИЛИ назначенному Главному судье (Суперпользователю можно всё)
            if not (is_creator or is_assigned_chief or request.user.is_superuser):
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Отказано в доступе: вы не привязаны к этому турниру.'}, status=400)
                    
                messages.error(request, "🛑 Отказано в доступе: Вы не являетесь организатором или главным судьей этого турнира.")
                return redirect('dashboard')
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def stage_access_lock(view_func):
    """
    Умный декоратор для этапов соревнований:
    Пускает Создателя турнира, Главного судью, Назначенных на этап судей и Автора результата.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
            
        stage = None
        is_author = False
        
        # Определяем, к какому этапу стучится пользователь
        if 'stage_id' in kwargs:
            stage = get_object_or_404(Stage, pk=kwargs['stage_id'])
        elif 'result_id' in kwargs:
            result = get_object_or_404(Result, pk=kwargs['result_id'])
            stage = result.stage
            is_author = (result.judge == request.user) # Если это редактирование, проверяем авторство

        if stage:
            comp = stage.competition
            is_owner = (comp.created_by == request.user)
            is_chief = (comp.chief_judge == request.user)
            is_assigned = stage.judges.filter(id=request.user.id).exists()
            
            # Если ни одно из условий не выполнено - выгоняем
            if not (is_owner or is_chief or is_assigned or is_author):
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Отказано в доступе к этапу.'}, status=403)
                messages.error(request, "🛑 У вас нет прав для работы с результатами этого этапа.")
                return redirect('dashboard')
                
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# ==========================================
# 2. ОБЩИЕ МАРШРУТЫ
# ==========================================

@login_required
def dashboard(request):
    """Главное меню системы"""
    return render(request, 'competitions/dashboard.html')

@login_required
def logout_view(request):
    logout(request)
    return redirect('login')


# ==========================================
# 3. БЛОК ПОЛЕВОГО СУДЬИ (ВВОД ДАННЫХ)
# ==========================================

@login_required
def stage_list(request):
    """Выбор активного этапа для судейства"""
    qs = Stage.objects.filter(competition__is_archived=False).select_related('competition', 'type')

    # УМНАЯ ФИЛЬТРАЦИЯ: Полевой судья видит ТОЛЬКО свои этапы
    if not request.user.is_superuser and request.user.role:
        if request.user.role.role_name == 'Судья':
            qs = qs.filter(judges=request.user)

    stages = qs.order_by('competition__title', 'id')
    return render(request, 'competitions/stage_list.html', {'stages': stages})

@login_required
@archive_lock
@stage_access_lock
def enter_result(request, stage_id):
    """Интерфейс ввода результатов участникам с поддержкой AJAX и офлайн-синхронизации"""
    stage = get_object_or_404(Stage, pk=stage_id)

    # ЗАЩИТА: Блокировка ввода, если турнир находится в архиве
    if stage.competition.is_archived:
        messages.error(request, "Соревнование архивировано. Ввод результатов невозможен.")
        return redirect('stage_list')

    if request.method == 'POST':
        # Проверяем, является ли запрос AJAX-запросом (от нашего PWA-скрипта)
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Получаем данные из запроса
        form = ResultForm(request.POST)
        
        if form.is_valid():
            result = form.save(commit=False)
                        
            # === ЗАЩИТА ОТ КРАЖИ УЧАСТНИКА (Mass Assignment) ===
            if result.participant.competition != stage.competition:
                messages.error(request, "🛑 Критическая ошибка: Попытка привязать участника из другого турнира!")
                return redirect('enter_result', stage_id=stage.id)
            # ===================================================

            # ЗАЩИТА: Запрет на дублирование результатов (Race Condition)
            # ЗАЩИТА: Запрет на дублирование результатов
            # Это первичная (мягкая) проверка
            if Result.objects.filter(participant=result.participant, stage=stage).exists():
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'Результат для этого участника уже зафиксирован!'}, status=400)
                messages.error(request, 'Результат для этого участника уже зафиксирован!')
            else:
                result.stage = stage
                
                # === ЗАЩИТА ОТ ПОДМЕНЫ ПОЛЕЙ (Mass Assignment) ===
                result.judge = request.user
                result.is_verified = False # ЖЕСТКО сбрасываем статус
                # ==================================================
                
                # 🛡️ УЛЬТРА-ЗАЩИТА ОТ ГОНКИ AJAX-ЗАПРОСОВ (Race Condition)
                try:
                    result.save()
                    
                    # Логируем действие для Организатора (ТОЛЬКО если сохранение прошло успешно)
                    AuditLog.objects.create(
                        user=request.user,
                        competition=stage.competition,
                        action="Ввод результата",
                        details=f"Судья зафиксировал результат для {result.participant.full_name} на этапе «{stage.name}»: {result.value}."
                    )
                    
                    # Если это был AJAX, просто подтверждаем успех
                    if is_ajax:
                        return JsonResponse({'success': True})
                    
                    # Если обычная отправка
                    messages.success(request, f"Результат для {result.participant.full_name} успешно записан!")
                    return redirect('enter_result', stage_id=stage.id)

                except IntegrityError:
                    # Если два запроса проскочили первую проверку .exists() одновременно, 
                    # второй запрос гарантированно разобьется об этот блок, а сервер НЕ упадет!
                    if is_ajax:
                        return JsonResponse({'success': False, 'error': 'Результат уже был отправлен ранее (дубликат синхронизации).'}, status=400)
                    messages.error(request, 'Критическая ошибка: Результат уже существует (дубликат).')
        else:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Некорректные данные формы. Проверьте значения.'}, status=400)

    # ==========================================
    # ОБРАБОТКА GET-ЗАПРОСА (Отрисовка страницы)
    # ==========================================
    
    # 1. Прямая и безопасная выборка ID спортсменов (исправляет баг с выпадающим списком после удаления)
    already_submitted_ids = Result.objects.filter(stage=stage).values_list('participant_id', flat=True)
    
    # 2. Передаем в шаблон только тех, кто еще НЕ сдавал этот этап
    participants = Participant.objects.filter(competition=stage.competition).exclude(id__in=already_submitted_ids).order_by('full_name')
    
    # 3. Выборка результатов для таблицы (теперь показываем ВСЕ результаты этапа)
    # Добавили select_related для оптимизации базы данных
    results = Result.objects.filter(stage=stage).select_related('participant', 'judge').order_by('-id')
    
    return render(request, 'competitions/enter_result.html', {
        'stage': stage, 
        'participants': participants, 
        'results': results
    })

@login_required
@archive_lock
@stage_access_lock
def edit_result(request, result_id):
    """Редактирование результата (совместный доступ для судей этапа)"""
    # 1. Получаем результат без жесткой привязки к автору
    result = get_object_or_404(Result, pk=result_id)
    stage = result.stage
    stage_id = stage.id

    # ЗАЩИТА БИЗНЕС-ЛОГИКИ: Блокируем редактирование проверенных результатов
    if result.is_verified:
        messages.error(request, "Этот результат уже утвержден Главным судьей. Изменения невозможны.")
        return redirect('enter_result', stage_id=stage_id)

    if request.method == 'POST':
        form = ResultForm(request.POST, instance=result)
        form.fields['participant'].queryset = Participant.objects.filter(id=result.participant.id)
        if form.is_valid():
            # === ЗАЩИТА ОТ ПОДМЕНЫ ПОЛЕЙ ===
            # 1. Останавливаем прямое сохранение
            safe_result = form.save(commit=False)
            
            # 2. Жестко перезаписываем критические поля
            safe_result.judge = request.user  # Автором правки становится тот, кто ее внес
            safe_result.is_verified = False   # Любая правка автоматически снимает верификацию!
            
            # 3. Теперь сохраняем в базу
            safe_result.save()
            # ===============================
            AuditLog.objects.create(
                user=request.user,
                competition=result.participant.competition,
                action="Редактирование результата",
                details=f"Судья изменил результат участника {result.participant.full_name} на этапе «{result.stage.name}»."
            )
            messages.success(request, f"Результат участника {result.participant.full_name} успешно исправлен.")
            return redirect('enter_result', stage_id=stage_id)
    else:
        form = ResultForm(instance=result)
        # УМНЫЙ ФИЛЬТР: Оставляем в выпадающем списке только этого участника, чтобы судья не мог случайно передать результат другому
        form.fields['participant'].queryset = Participant.objects.filter(id=result.participant.id)

    return render(request, 'competitions/generic_edit.html', {
        'form': form, 
        'title': 'Исправление результата'
    })

@login_required
def stage_leaderboard(request, stage_id):
    """Просмотр турнирной таблицы конкретного этапа"""
    stage = get_object_or_404(Stage, pk=stage_id)
    standings = calculate_stage_standings(stage.id)
    return render(request, 'competitions/leaderboard.html', {'stage': stage, 'standings': standings})


# ==========================================
# 4. БЛОК ГЛАВНОГО СУДЬИ (ВЕРИФИКАЦИЯ)
# ==========================================

@login_required
@chief_judge_required  # Используем твою переменную-декоратор для защиты доступа
def chief_stage_list(request):
    """
    Список этапов для верификации (Multi-tenant):
    Организатор видит этапы СВОИХ турниров, Главный судья — тех, куда он НАЗНАЧЕН.
    """
    if request.user.is_superuser:
        stages = Stage.objects.filter(competition__is_archived=False)
    else:
        # Умная фильтрация через Q-объект:
        # Выбираем этапы, где создатель турнира текущий пользователь ИЛИ он же назначен Главным судьей
        stages = Stage.objects.filter(competition__is_archived=False).filter(
            Q(competition__created_by=request.user) | Q(competition__chief_judge=request.user)
        ).distinct() # .distinct() исключит дубли, если организатор назначил главным судьей самого себя
        
    return render(request, 'competitions/chief_stage_list.html', {'stages': stages})

@login_required
@chief_judge_required
@owner_lock
@archive_lock
def stage_verify_panel(request, stage_id):
    """Панель проверки и утверждения результатов этапа"""
    stage = get_object_or_404(Stage, pk=stage_id)
    results = Result.objects.filter(stage=stage).select_related('participant', 'judge').order_by('is_verified', '-created_at')
    return render(request, 'competitions/stage_verify.html', {'stage': stage, 'results': results})

@login_required
@chief_judge_required
@safe_require_POST
@owner_lock
@archive_lock
def verify_results_backend(request, stage_id):
    """Обработчик действий: Верификация, Штраф, Удаление, Отмена верификации + Массовые действия"""
    stage = get_object_or_404(Stage, pk=stage_id)
    action = request.POST.get('action')

    # === 1. МАССОВЫЕ ДЕЙСТВИЯ (Не требуют конкретного result_id) ===
    
    if action == 'verify_all':
        # Выбираем только те результаты этапа, которые еще не верифицированы
        unverified_results = Result.objects.filter(stage=stage, is_verified=False)
        count = unverified_results.count()
        
        if count > 0:
            # Быстрое обновление в базе данных одним SQL-запросом
            unverified_results.update(is_verified=True)
            
            # Пишем в системный журнал
            AuditLog.objects.create(
                user=request.user, 
                competition=stage.competition,
                action="Массовая верификация",
                details=f"Главный судья массово утвердил все ожидающие результаты ({count} шт.) на этапе «{stage.name}»."
            )
            messages.success(request, f"Все ожидающие результаты ({count} шт.) успешно подтверждены.")
        else:
            messages.info(request, "На этом этапе нет результатов, ожидающих проверки.")
            
        return redirect('stage_verify_panel', stage_id=stage.id)

    elif action == 'delete_all':
        # Выбираем абсолютно все результаты этого этапа
        all_results = Result.objects.filter(stage=stage)
        count = all_results.count()
        
        if count > 0:
            all_results.delete()
            
            # Пишем в системный журнал
            AuditLog.objects.create(
                user=request.user, 
                competition=stage.competition,
                action="Массовое удаление результатов",
                details=f"Главный судья полностью очистил этап «{stage.name}», безвозвратно удалив {count} результатов."
            )
            messages.success(request, f"Все результаты этапа ({count} шт.) были безвозвратно удалены.")
        else:
            messages.info(request, "На этом этапе пока нет результатов для удаления.")
            
        return redirect('stage_verify_panel', stage_id=stage.id)


    # === 2. ОДИНОЧНЫЕ ДЕЙСТВИЯ (Требуют конкретный объект и result_id) ===
    
    result_id = request.POST.get('result_id')
    res = get_object_or_404(Result, pk=result_id, stage=stage) # ✅ БЕЗОПАСНО

    if action == 'verify':
        res.is_verified = True
        res.save()
        AuditLog.objects.create(
            user=request.user, competition=res.participant.competition,
            action="Верификация результата",
            details=f"Главный судья подтвердил результат участника {res.participant.full_name} на этапе «{res.stage.name}»."
        )
        messages.success(request, f"Результат участника {res.participant.full_name} успешно подтвержден.")

    elif action == 'unverify':
        res.is_verified = False
        res.save()
        AuditLog.objects.create(
            user=request.user, competition=res.participant.competition,
            action="Отмена верификации",
            details=f"Главный судья снял верификацию с результата участника {res.participant.full_name} на этапе «{res.stage.name}»."
        )
        messages.warning(request, f"Верификация снята. Результат {res.participant.full_name} снова доступен для редактирования судьями.")

    elif action == 'edit_penalty':
        new_penalty_raw = request.POST.get('new_penalty', '0')
        reason = request.POST.get('reason', 'Корректировка Главным судьей')
        
        try:
            new_penalty = abs(float(new_penalty_raw.replace(',', '.')))
        except ValueError:
            messages.error(request, "Ошибка: Неверный формат штрафа. Введите число.")
            return redirect('stage_verify_panel', stage_id=stage.id)
        
        ResultLog.objects.create(
            result=res, changed_by=request.user,
            old_value=res.penalty_value, new_value=new_penalty, comment=reason
        )
        res.penalty_value = new_penalty
        res.is_verified = True 
        res.save()
        
        AuditLog.objects.create(
            user=request.user, competition=res.participant.competition,
            action="Корректировка результата",
            details=f"Изменен штраф участнику {res.participant.full_name} на {new_penalty}. Причина: {reason}."
        )
        messages.success(request, f"Штраф участника {res.participant.full_name} изменен, результат утвержден.")

    elif action == 'delete':
        AuditLog.objects.create(
            user=request.user, competition=res.participant.competition,
            action="Удаление результата",
            details=f"Главный судья удалил результат участника {res.participant.full_name} на этапе «{res.stage.name}»."
        )
        res.delete()
        messages.success(request, "Результат был безвозвратно удален.")

    return redirect('stage_verify_panel', stage_id=stage.id)


# ==========================================
# 5. БЛОК ОРГАНИЗАТОРА (УПРАВЛЕНИЕ)
# ==========================================

@login_required
@organizer_required
def organizer_competitions(request):
    qs = Competition.objects.filter(is_archived=False)
    # Если это не супермен, показываем только его личные турниры
    if not request.user.is_superuser:
        qs = qs.filter(created_by=request.user)
        
    competitions = qs.order_by('-start_date')
    return render(request, 'competitions/organizer_list.html', {'competitions': competitions})

@login_required
@organizer_required
@owner_lock
@archive_lock
def competition_panel(request, comp_id):
    """Хаб управления турниром"""
    competition = get_object_or_404(Competition, pk=comp_id)
    stats = {
        'stages': competition.stages.count(),
        'participants': competition.participants.count(),
        'teams': competition.teams.count(),
    }
    return render(request, 'competitions/competition_panel.html', {'competition': competition, 'stats': stats})

@login_required
@organizer_required
def create_competition(request):
    if request.method == 'POST':
        form = CompetitionForm(request.POST)
        if form.is_valid():
            comp = form.save(commit=False)
            comp.created_by = request.user
            comp.save()
            AuditLog.objects.create(
                user=request.user, competition=comp, action="Создание соревнования",
                details=f"Создано соревнование: «{comp.title}»."
            )
            return redirect('organizer_competitions')
    else:
        form = CompetitionForm()
    return render(request, 'competitions/create_competition.html', {'form': form, 'edit_mode': False})

@login_required
@organizer_required
@owner_lock
@archive_lock
def edit_competition(request, comp_id):
    """Редактирование настроек турнира с защитой моделей расчета этапов"""
    comp = get_object_or_404(Competition, pk=comp_id)
    old_type_id = comp.type_id  # Запоминаем старую категорию до изменений
    
    if request.method == 'POST':
        form = CompetitionForm(request.POST, instance=comp)
        if form.is_valid():
            updated_comp = form.save(commit=False)
            type_changed = (old_type_id != updated_comp.type_id)
            updated_comp.save()
            
            # --- УМНАЯ ЗАЩИТА АЛГОРИТМОВ ПРИ СМЕНЕ КАТЕГОРИИ ---
            if type_changed:
                reset_count = 0
                for stage in updated_comp.stages.all():
                    # Если меняется категория турнира, безопаснее всего сбросить 
                    # все "хитрые" формулы на базовую нормализацию, чтобы не было крашей
                    if stage.scoring_method != 'normalization':
                        stage.scoring_method = 'normalization'
                        stage.scoring_config = {}
                        stage.save()
                        reset_count += 1
                        
                if reset_count > 0:
                    messages.warning(
                        request, 
                        f"⚠️ Внимание! Из-за смены категории турнира, у {reset_count} этапов алгоритм расчета был сброшен на базовую 'Линейную нормализацию'. Проверьте их настройки."
                    )
            # ---------------------------------------------------
            
            AuditLog.objects.create(
                user=request.user, competition=updated_comp, action="Редактирование турнира",
                details=f"Организатор обновил параметры турнира «{updated_comp.title}»."
            )
            return redirect('competition_panel', comp_id=updated_comp.id)
    else:
        form = CompetitionForm(instance=comp)
    return render(request, 'competitions/create_competition.html', {'form': form, 'edit_mode': True})

@login_required
@organizer_required
@owner_lock
@archive_lock
def manage_stages(request, comp_id):
    competition = get_object_or_404(Competition, pk=comp_id)
    if request.method == 'POST':
        form = StageForm(request.POST, competition=competition)
        if form.is_valid():
            stage = form.save(commit=False)
            stage.competition = competition
            stage.save()
            AuditLog.objects.create(
                user=request.user, competition=competition, action="Создание этапа",
                details=f"Добавлен этап: «{stage.name}»."
            )
            return redirect('manage_stages', comp_id=competition.id)
    else:
        form = StageForm(competition=competition)
    stages = competition.stages.all().select_related('type')
    return render(request, 'competitions/manage_stages.html', {'competition': competition, 'form': form, 'stages': stages})

@login_required
@organizer_required
@owner_lock
@archive_lock
def manage_participants(request, comp_id):
    competition = get_object_or_404(Competition, pk=comp_id)
    if request.method == 'POST':
        # --- НОВОЕ: Обработка массового удаления ---
        if request.POST.get('action') == 'delete_all':
            participants_to_delete = competition.participants.all()
            count = participants_to_delete.count()
            if count > 0:
                try:
                    participants_to_delete.delete()
                    AuditLog.objects.create(
                        user=request.user, competition=competition, action="Массовое удаление",
                        details=f"Организатор массово удалил ВСЕХ участников ({count} шт.) турнира."
                    )
                    messages.success(request, f"Все участники ({count} шт.) успешно удалены из базы.")
                except ProtectedError:
                    messages.error(request, "🛑 Ошибка: Невозможно удалить всех участников, так как у некоторых уже есть результаты! Сначала очистите протоколы этапов.")
            else:
                messages.info(request, "База участников уже пуста.")
            return redirect('manage_participants', comp_id=competition.id)
        # -------------------------------------------

        form = ParticipantForm(request.POST)
        if form.is_valid():
            participant = form.save(commit=False)
            participant.competition = competition
            participant.save()
            AuditLog.objects.create(
                user=request.user, competition=competition, action="Добавление участника",
                details=f"Зарегистрирован: {participant.full_name} (Бейдж: {participant.bib_number})."
            )
            return redirect('manage_participants', comp_id=competition.id)
    else:
        form = ParticipantForm()
    participants = competition.participants.all().order_by('bib_number')
    return render(request, 'competitions/manage_participants.html', {'competition': competition, 'form': form, 'participants': participants})

@login_required
@organizer_required
@owner_lock
@archive_lock
def manage_teams(request, comp_id):
    competition = get_object_or_404(Competition, pk=comp_id)
    if request.method == 'POST':

        # --- НОВОЕ: Обработка массового расформирования команд ---
        if request.POST.get('action') == 'delete_all':
            teams_to_delete = competition.teams.all()
            count = teams_to_delete.count()
            if count > 0:
                teams_to_delete.delete()
                AuditLog.objects.create(
                    user=request.user, competition=competition, action="Массовое удаление команд",
                    details=f"Организатор расформировал ВСЕ команды ({count} шт.) турнира."
                )
                messages.success(request, f"Все команды ({count} шт.) успешно расформированы. Спортсмены остались в базе.")
            else:
                messages.info(request, "В турнире пока нет команд.")
            return redirect('manage_teams', comp_id=competition.id)
        # ---------------------------------------------------------

        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.competition = competition
            team.save()
            AuditLog.objects.create(user=request.user, competition=competition, action="Создание команды", details=f"Создана команда: «{team.team_name}».")
            return redirect('manage_teams', comp_id=competition.id)
    else:
        form = TeamForm()
    teams = competition.teams.all()
    return render(request, 'competitions/manage_teams.html', {'competition': competition, 'form': form, 'teams': teams})

@login_required
@organizer_required
@owner_lock
@archive_lock
def manage_team_members(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    competition = team.competition
    
    if request.method == 'POST':
        # --- НОВОЕ: Обработка массового исключения из команды ---
        if request.POST.get('action') == 'delete_all':
            members_to_delete = team.members.all()
            count = members_to_delete.count()
            if count > 0:
                members_to_delete.delete()
                AuditLog.objects.create(
                    user=request.user, competition=competition, 
                    action="Очистка состава команды", 
                    details=f"Организатор удалил всех участников ({count} шт.) из команды «{team.team_name}»."
                )
                messages.success(request, f"Состав очищен. Все участники ({count} шт.) успешно исключены из команды.")
            else:
                messages.info(request, "В этой команде пока нет участников.")
            return redirect('manage_team_members', team_id=team.id)
        # --------------------------------------------------------

        form = TeamMemberForm(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.team = team

            # === ЗАЩИТА ОТ КРАЖИ УЧАСТНИКА В ЧУЖУЮ КОМАНДУ ===
            if member.participant.competition != competition:
                messages.error(request, "🛑 Критическая ошибка: Этот спортсмен из другого турнира!")
                return redirect('manage_team_members', team_id=team.id)
            # =================================================
            
            # Защита от дублей
            if TeamMember.objects.filter(team__competition=competition, participant=member.participant).exists():
                messages.error(request, 'Ошибка: Этот участник уже состоит в одной из команд!')
            else:
                member.save()
                AuditLog.objects.create(
                    user=request.user, competition=competition, 
                    action="Состав команды", 
                    details=f"{member.participant.full_name} добавлен в команду «{team.team_name}»."
                )
                messages.success(request, f"Участник {member.participant.full_name} успешно зачислен в состав.")
                return redirect('manage_team_members', team_id=team.id)
    else:
        form = TeamMemberForm()
        
        # УМНЫЙ ФИЛЬТР: Получаем ID всех участников, которые УЖЕ состоят в ЛЮБЫХ командах этого турнира
        assigned_participants = TeamMember.objects.filter(
            team__competition=competition
        ).values_list('participant_id', flat=True)
        
        # Отдаем в форму только "свободных" спортсменов
        form.fields['participant'].queryset = competition.participants.exclude(
            id__in=assigned_participants
        ).order_by('full_name')
        
    members = team.members.select_related('participant').all()
    return render(request, 'competitions/manage_team_members.html', {
        'team': team, 
        'competition': competition, 
        'form': form, 
        'members': members
    })

@login_required
@organizer_required
@owner_lock
@archive_lock
def edit_participant(request, part_id):
    participant = get_object_or_404(Participant, pk=part_id)
    if request.method == 'POST':
        form = ParticipantForm(request.POST, instance=participant)
        if form.is_valid():
            part = form.save(commit=False)
            
            # ЗАЩИТА ОТ 500: Проверяем на дубликат, ИСКЛЮЧАЯ самого себя (exclude)
            if part.bib_number and Participant.objects.exclude(pk=part.pk).filter(competition=participant.competition, bib_number=part.bib_number).exists():
                messages.error(request, f"Ошибка: Стартовый номер «{part.bib_number}» уже занят другим спортсменом!")
            else:
                part.save()
                AuditLog.objects.create(user=request.user, competition=participant.competition, action="Редактирование", details=f"Изменены данные участника: {part.full_name}")
                messages.success(request, f"Данные спортсмена {part.full_name} успешно обновлены.")
                return redirect('manage_participants', comp_id=participant.competition.id)
    else:
        form = ParticipantForm(instance=participant)
    return render(request, 'competitions/generic_edit.html', {'form': form, 'title': 'Редактирование участника'})

@login_required
@organizer_required
@owner_lock
@archive_lock
def edit_stage(request, stage_id):
    stage = get_object_or_404(Stage, pk=stage_id)
    if request.method == 'POST':
        form = StageForm(request.POST, instance=stage, competition=stage.competition)
        if form.is_valid():
            form.save()
            AuditLog.objects.create(user=request.user, competition=stage.competition, action="Редактирование", details=f"Изменено название этапа: {stage.name}")
            messages.success(request, f"Этап {stage.name} успешно обновлен.")
            return redirect('manage_stages', comp_id=stage.competition.id)
    else:
        form = StageForm(instance=stage, competition=stage.competition)
    # ИСПРАВЛЕНИЕ: Теперь используем специализированный шаблон вместо generic_edit.html
    return render(request, 'competitions/edit_stage.html', {'form': form, 'stage': stage, 'title': 'Редактирование этапа'})

@login_required
@organizer_required
@owner_lock
@archive_lock
def edit_team(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            form.save()
            messages.success(request, f"Команда {team.team_name} успешно обновлена.")
            return redirect('manage_teams', comp_id=team.competition.id)
    else:
        form = TeamForm(instance=team)
    return render(request, 'competitions/generic_edit.html', {'form': form, 'title': 'Редактирование команды'})


# ==========================================
# 6. УДАЛЕНИЕ СТРУКТУР (DELETE ACTIONS)
# ==========================================

@login_required
@organizer_required
@owner_lock
@safe_require_POST
@archive_lock
def delete_competition(request, comp_id):
    comp = get_object_or_404(Competition, pk=comp_id)
    try:
        comp_title = comp.title
        comp.delete()
        AuditLog.objects.create(
            user=request.user, 
            competition=None, 
            action="Удаление соревнования", 
            details=f"СИСТЕМНОЕ УДАЛЕНИЕ: «{comp_title}»."
        )
        messages.success(request, f"Соревнование «{comp_title}» и все пустые этапы успешно удалены.")
    except ProtectedError:
        messages.error(
            request, 
            f"Невозможно удалить турнир «{comp.title}», так как внутри него есть этапы с уже зафиксированными результатами! Сначала удалите результаты, либо просто перенесите турнир в Архив."
        )
        
    return redirect('organizer_competitions')

@login_required
@organizer_required
@owner_lock
@safe_require_POST
@archive_lock
def delete_stage(request, stage_id):
    stage = get_object_or_404(Stage, pk=stage_id)
    comp_id = stage.competition.id
    try:
        stage_name = stage.name
        stage.delete()
        AuditLog.objects.create(user=request.user, competition=stage.competition, action="Удаление этапа", details=f"Удален этап «{stage_name}».")
        messages.success(request, f"Этап «{stage_name}» успешно удален.")
    except ProtectedError:
        messages.error(request, f"Невозможно удалить этап «{stage.name}», так как в нем уже зафиксированы результаты участников!")
    
    return redirect('manage_stages', comp_id=comp_id)


@login_required
@organizer_required
@owner_lock
@safe_require_POST
@archive_lock
def delete_participant(request, part_id):
    participant = get_object_or_404(Participant, pk=part_id)
    comp_id = participant.competition.id
    try:
        part_name = participant.full_name
        participant.delete()
        AuditLog.objects.create(user=request.user, competition=participant.competition, action="Удаление участника", details=f"Удален {part_name}.")
        messages.success(request, f"Участник {part_name} успешно удален из базы.")
    except ProtectedError:
        messages.error(request, f"Невозможно удалить участника {participant.full_name}, так как он уже имеет зафиксированные результаты!")
    
    return redirect('manage_participants', comp_id=comp_id)


@login_required
@organizer_required
@owner_lock
@safe_require_POST
@archive_lock
def delete_team(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    comp_id = team.competition.id
    try:
        team_name = team.team_name
        team.delete()
        AuditLog.objects.create(user=request.user, competition=team.competition, action="Удаление команды", details=f"Удалена команда «{team_name}».")
        messages.success(request, f"Команда «{team_name}» успешно удалена.")
    except ProtectedError:
        # У команд обычно CASCADE с участниками, но на всякий случай защищаем
        messages.error(request, f"Невозможно удалить команду «{team.team_name}», так как с ней связаны другие данные!")
        
    return redirect('manage_teams', comp_id=comp_id)

@login_required
@organizer_required
@owner_lock
@safe_require_POST
@archive_lock
def delete_team_member(request, member_id):
    member = get_object_or_404(TeamMember, pk=member_id)
    team_id = member.team.id
    AuditLog.objects.create(user=request.user, competition=member.team.competition, action="Исключение из команды", details=f"{member.participant.full_name} исключен из «{member.team.team_name}».")
    member.delete()
    return redirect('manage_team_members', team_id=team_id)


# ==========================================
# 7. СВОДНЫЕ ОТЧЕТЫ, EXCEL, PDF И АРХИВЫ
# ==========================================

def get_smart_summary(competition):
    """
    Сборка итоговой таблицы на основе заработанных БАЛЛОВ (Math Engine).
    Чем больше баллов, тем выше место.
    """
    individual_summary = []
    team_summary = []
    
    participants = competition.participants.all()
    stages = competition.stages.all()
    
    # 1. Инициализируем базовую структуру для каждого спортсмена
    p_scores = {
        p.id: {
            'participant': p, 
            'final_score': 0, 
            'total_penalty': 0, 
            'has_results': False,
            'stages': {}  # <--- ИСПРАВЛЕНИЕ: Добавили пустой словарь для хранения этапов
        } for p in participants
    }
    
    # 2. Расчет личного зачета по сумме БАЛЛОВ
    for stage in stages:
        # Получаем данные из нашего Math Engine (ScoringFactory)
        standings = calculate_stage_standings(stage.id)
        
        for row in standings:
            p_id = row['participant'].id
            
            p_scores[p_id]['final_score'] += row['points'] 
            p_scores[p_id]['total_penalty'] += row['penalty']
            p_scores[p_id]['has_results'] = True
            
            # Теперь KeyError здесь не возникнет
            p_scores[p_id]['stages'][stage.id] = {
                'value': row['original_value'],
                'points': row['points'],
                'place': row['place']
            }

    # Сортировка личного зачета: 
    # сначала те, у кого есть результаты, затем по УБЫВАНИЮ баллов (минус перед x['final_score'])
    individual_summary = list(p_scores.values())
    individual_summary.sort(key=lambda x: (not x['has_results'], -x['final_score']))

    # --- ДОБАВЛЯЕМ ЭТОТ БЛОК РАСЧЕТА МЕСТ ---
    for i, row in enumerate(individual_summary):
        if not row['has_results']:
            row['place'] = '-'
        elif i > 0 and row['final_score'] == individual_summary[i-1]['final_score']:
            row['place'] = individual_summary[i-1]['place'] # Дублируем место при равенстве баллов
        else:
            row['place'] = i + 1

    # 3. Расчет командного зачета
    if competition.has_team:
        teams = competition.teams.prefetch_related('members__participant').all()
        for team in teams:
            team_score = 0
            members_count = 0
            for member in team.members.all():
                p_data = p_scores.get(member.participant.id)
                if p_data and p_data['has_results']:
                    team_score += p_data['final_score']
                    members_count += 1
                    
            team_summary.append({
                'team': team.team_name,
                'members_count': members_count,
                'team_score': team_score
            })
            
        # Сортировка команд: пустые команды вниз, остальные по УБЫВАНИЮ баллов
        team_summary.sort(key=lambda x: (x['members_count'] == 0, -x['team_score']))

        # --- ДОБАВЛЯЕМ ЭТОТ БЛОК РАСЧЕТА МЕСТ ДЛЯ КОМАНД ---
        for i, row in enumerate(team_summary):
            if row['members_count'] == 0:
                row['place'] = '-'
            elif i > 0 and row['team_score'] == team_summary[i-1]['team_score']:
                row['place'] = team_summary[i-1]['place'] # Дублируем место при равенстве
            else:
                row['place'] = i + 1

    return individual_summary, team_summary


@login_required
@organizer_required
@owner_lock
def competition_summary(request, comp_id):
    competition = get_object_or_404(Competition, pk=comp_id)
    individual_summary, team_summary = get_smart_summary(competition)
    
    return render(request, 'competitions/summary.html', {
        'competition': competition,
        'individual_summary': individual_summary,
        'team_summary': team_summary
    })

@login_required
@organizer_required
@owner_lock
def print_protocol(request, comp_id):
    competition = get_object_or_404(Competition, pk=comp_id)
    individual_summary, team_summary = get_smart_summary(competition)
    
    return render(request, 'competitions/print_protocol.html', {
        'competition': competition,
        'individual_summary': individual_summary,
        'team_summary': team_summary
    })

@login_required
@organizer_required
@owner_lock
def export_csv_report(request, comp_id):
    """Выгрузка СВОДНОГО отчета (Сумма мест) в Excel"""
    competition = get_object_or_404(Competition, pk=comp_id)
    individual_summary, _ = get_smart_summary(competition)
    
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="Summary_{competition.id}.csv"'
    writer = csv.writer(response, delimiter=';')
    
    writer.writerow(['Соревнование:', competition.title, 'Дата:', competition.start_date])
    writer.writerow(['Место', 'Стартовый номер', 'ФИО Участника', 'Общий штраф', 'Сумма занятых мест'])
    
    for index, row in enumerate(individual_summary):
        if row['has_results']:
            # ИСПРАВЛЕНИЕ: берем данные из row['final_score']
            writer.writerow([index + 1, row['participant'].bib_number, row['participant'].full_name, row['total_penalty'], row['final_score']])
    return response

@login_required
@organizer_required
@owner_lock
def export_xlsx_report(request, comp_id):
    """Выгрузка СВОДНОГО отчета в настоящем формате Excel (.xlsx)"""
    competition = get_object_or_404(Competition, pk=comp_id)
    individual_summary, _ = get_smart_summary(competition)
    
    # Создаем новый Excel-документ
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Итоги турнира"
    
    # Записываем шапку
    sheet.append(['Соревнование:', competition.title, 'Дата:', str(competition.start_date)])
    sheet.append([]) # Пустая строка для отступа
    sheet.append(['Место', 'Стартовый номер', 'ФИО Участника', 'Общий штраф', 'Сумма занятых мест'])
    
    # Записываем данные спортсменов
    for index, row in enumerate(individual_summary):
        if row['has_results']:
            sheet.append([
                index + 1, 
                row['participant'].bib_number, 
                row['participant'].full_name, 
                float(row['total_penalty']), 
                float(row['final_score'])
            ])
            
    # Настраиваем HTTP-ответ
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Summary_{competition.id}.xlsx"'
    
    # Сохраняем файл в ответ браузеру
    workbook.save(response)
    return response

@login_required
@organizer_required
@owner_lock
def export_excel(request, comp_id):
    """Выгрузка СЫРЫХ результатов всех этапов в Excel (Из Архива)"""
    comp = get_object_or_404(Competition, id=comp_id)
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="Raw_Results_{comp.id}.csv"'
    writer = csv.writer(response, delimiter=';')
    
    writer.writerow(['ФИО Участника', 'Номер (Бейдж)', 'Название этапа', 'Результат', 'Штраф'])
    results = Result.objects.filter(participant__competition=comp, is_verified=True).select_related('participant', 'stage')
    for r in results:
        val_str = str(r.value).replace('.', ',')
        # Если штрафа нет (None), пишем '0', иначе превращаем точку в запятую
        pen_val = r.penalty_value if r.penalty_value is not None else 0
        pen_str = str(pen_val).replace('.', ',')
        
        writer.writerow([r.participant.full_name, r.participant.bib_number, r.stage.name, val_str, pen_str])

@login_required
@organizer_required
@owner_lock
@safe_require_POST
def toggle_archive(request, comp_id):
    comp = get_object_or_404(Competition, id=comp_id)
    
    # Инвертируем статус (если был False, станет True, и наоборот)
    comp.is_archived = not comp.is_archived
    comp.save()
    
    if comp.is_archived:
        AuditLog.objects.create(user=request.user, competition=comp, action="Архивация", details=f"Турнир «{comp.title}» перенесен в архив.")
        messages.warning(request, f"Турнир «{comp.title}» заморожен и отправлен в архив.")
        return redirect('organizer_competitions')
    else:
        AuditLog.objects.create(user=request.user, competition=comp, action="Разархивация", details=f"Турнир «{comp.title}» восстановлен из архива.")
        messages.success(request, f"Турнир «{comp.title}» успешно восстановлен и снова доступен для судейства!")
        return redirect('archive_list')

@login_required
@organizer_required
def archive_list(request):
    qs = Competition.objects.filter(is_archived=True)
    
    # ЗАЩИТА: Показываем организатору только его личный архив
    if not request.user.is_superuser:
        qs = qs.filter(created_by=request.user)
        
    archived_comps = qs.order_by('-start_date')
    return render(request, 'competitions/archive_list.html', {'competitions': archived_comps})

@login_required
@organizer_required
@owner_lock
def archive_detail(request, comp_id):
    comp = get_object_or_404(Competition, id=comp_id, is_archived=True)
    stages = Stage.objects.filter(competition=comp).order_by('id')
    teams = Team.objects.filter(competition=comp).order_by('team_name')
    participants = Participant.objects.filter(competition=comp).order_by('full_name')
    return render(request, 'competitions/archive_detail.html', {'competition': comp, 'stages': stages, 'teams': teams, 'participants': participants})

@login_required
@organizer_required
def audit_log_list(request):
    qs = AuditLog.objects.select_related('user', 'competition')
    
    # ЗАЩИТА АУДИТА: Суперпользователь видит всё. 
    # Остальные видят логи СВОИХ турниров ИЛИ логи СВОИХ действий (например, факт удаления).
    if not request.user.is_superuser:
        qs = qs.filter(
            Q(competition__created_by=request.user) | Q(user=request.user)
        )
        
    logs = qs.order_by('-timestamp')[:200]
    return render(request, 'competitions/audit_log.html', {'logs': logs})

@login_required
def offline_manifest(request):
    """
    Генератор списка всех доступных пользователю страниц для PWA предзагрузки.
    Умная генерация ссылок на основе ролей (Защита от AttributeError).
    """
    # 1. БЕЗОПАСНОЕ извлечение роли (если роли нет, возвращаем пустую строку)
    user_role = request.user.role.role_name if request.user.role else ""
    is_super = request.user.is_superuser

    # 2. Базовые URL для всех авторизованных (включая рядовых судей)
    urls = [
        reverse('dashboard'),
        reverse('stage_list'),
    ]

    # 3. Разделы Главного судьи / Организатора (для верификации результатов)
    # Организатор и Главный судья теперь оба предзагружают общую страницу верификации
    if user_role in ["Главный судья", "Организатор"] or is_super:
        urls.append(reverse('chief_stage_list'))

    # 4. Глобальные разделы Организатора
    if user_role == "Организатор" or is_super:
        urls.append(reverse('audit_log_list'))
        urls.append(reverse('archive_list'))
        urls.append(reverse('organizer_competitions'))

    # 5. Собираем динамические ссылки для активных соревнований
    competitions = Competition.objects.filter(is_archived=False)
    for comp in competitions:
        is_owner = (comp.created_by == request.user)
        is_assigned_chief = (comp.chief_judge == request.user)
        
        # Ссылку на Сводный отчет кэшируют только те, кто имеет отношение к турниру
        if is_super or is_owner or is_assigned_chief:
            urls.append(reverse('competition_summary', kwargs={'comp_id': comp.id}))
            
            # Полная панель управления структурой доступна ТОЛЬКО Организаторам-создателям турнира
            if is_super or (user_role == "Организатор" and is_owner):
                urls.append(reverse('competition_panel', kwargs={'comp_id': comp.id}))
                urls.append(reverse('manage_participants', kwargs={'comp_id': comp.id}))
                urls.append(reverse('manage_stages', kwargs={'comp_id': comp.id}))
                urls.append(reverse('manage_teams', kwargs={'comp_id': comp.id}))
                
                for team in comp.teams.all():
                    urls.append(reverse('manage_team_members', kwargs={'team_id': team.id}))

    # 6. Собираем ссылки на формы судейства и турнирные таблицы
    stages = Stage.objects.filter(competition__is_archived=False)

    # --- ЖЕСТКАЯ ФИЛЬТРАЦИЯ ДЛЯ PWA-КЭША ---
    if is_super:
        pass # Суперпользователь качает всё
    elif user_role == "Организатор":
        # Организатор качает этапы ТОЛЬКО своих турниров (или где он назначен главным)
        from django.db.models import Q
        stages = stages.filter(Q(competition__created_by=request.user) | Q(competition__chief_judge=request.user))
    elif user_role == "Главный судья":
        stages = stages.filter(competition__chief_judge=request.user)
    elif user_role == "Судья":
        stages = stages.filter(judges=request.user)
    else:
        stages = Stage.objects.none() # Безопасный дефолт: ничего не отдавать
    # ---------------------------------------

    for stage in stages:
        # Формы ввода и лидерборды доступны и кэшируются всеми (включая рядовых полевых судей)
        urls.append(reverse('enter_result', kwargs={'stage_id': stage.id}))
        urls.append(reverse('stage_leaderboard', kwargs={'stage_id': stage.id}))
        
        is_stage_owner = (stage.competition.created_by == request.user)
        is_stage_chief = (stage.competition.chief_judge == request.user)
        
        # ЗАЩИТА ПАНЕЛИ ВЕРИФИКАЦИИ В КЭШЕ PWA:
        # Организатор кэширует панели верификации только СВОИХ соревнований, 
        # а назначенный Главный судья — только ТЕХ, за которые он отвечает.
        if is_super:
            urls.append(reverse('stage_verify_panel', kwargs={'stage_id': stage.id}))
        elif user_role == "Организатор" and is_stage_owner:
            urls.append(reverse('stage_verify_panel', kwargs={'stage_id': stage.id}))
        elif user_role == "Главный судья" and is_stage_chief:
            urls.append(reverse('stage_verify_panel', kwargs={'stage_id': stage.id}))

    # Убираем дубликаты и возвращаем чистый JSON
    unique_urls = list(set(urls))
    return JsonResponse({'urls': unique_urls})