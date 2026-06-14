import random
from datetime import date
from django.contrib.auth import get_user_model
from django.db import transaction
from competitions.models import (
    Role, CompetitionType, Competition, StageType, Stage, 
    Participant, Team, TeamMember, Result, AuditLog, ResultLog
)

User = get_user_model()

def run_seed():
    print("🗑️ Начинаем очистку старых данных...")
    
    # 1. Удаляем связанные данные в правильном порядке (защита от ProtectedError)
    ResultLog.objects.all().delete()
    AuditLog.objects.all().delete()
    Result.objects.all().delete()
    TeamMember.objects.all().delete()
    Team.objects.all().delete()
    Participant.objects.all().delete()
    Stage.objects.all().delete()
    Competition.objects.all().delete()
    
    # Очищаем справочники, чтобы загрузить обновленные списки
    StageType.objects.all().delete()
    CompetitionType.objects.all().delete()
    
    # Удаляем всех обычных пользователей (оставляем только админов/суперюзеров)
    User.objects.filter(is_superuser=False).delete()
    print("✅ Старые данные успешно удалены.")

    # 2. Создаем или получаем роли
    role_org, _ = Role.objects.get_or_create(role_name=Role.RoleNames.ORGANIZER)
    role_chief, _ = Role.objects.get_or_create(role_name=Role.RoleNames.CHIEF_JUDGE)
    role_judge, _ = Role.objects.get_or_create(role_name=Role.RoleNames.JUDGE)

    # 3. Генерируем учетные записи
    print("👤 Создаем учетные записи персонала...")
    users_info = []

    org_user = User.objects.create_user(username="organizer1", password="password123", full_name="Иванов И.И. (Организатор)", role=role_org)
    users_info.append(("Организатор", "organizer1", "password123"))

    chief_user = User.objects.create_user(username="chief1", password="password123", full_name="Петров П.П. (Главный судья)", role=role_chief)
    users_info.append(("Главный судья", "chief1", "password123"))

    judges = []
    for i in range(1, 4):
        judge = User.objects.create_user(username=f"judge{i}", password="password123", full_name=f"Судья №{i} (Полевой)", role=role_judge)
        judges.append(judge)
        users_info.append((f"Полевой судья {i}", f"judge{i}", "password123"))

    # 4. Расширенный список категорий (на основе ВРВС)
    print("📋 Загружаем справочник видов спорта...")
    comp_types_data = [
        "Легкая атлетика",
        "Тяжелая атлетика",
        "Плавание",
        "Лыжные гонки",
        "Спортивная гимнастика",
        "Полиатлон (Многоборье)",
        "Спортивное ориентирование",
        "Триатлон",
        "Гиревой спорт",
        "Готов к труду и обороне (ГТО)",
        "Единоборства"
    ]
    comp_types = {}
    for ct_name in comp_types_data:
        ct = CompetitionType.objects.create(type_name=ct_name)
        comp_types[ct_name] = ct

    # 5. Расширенный список типов замеров
    print("📏 Создаем метрики и единицы измерения...")
    stage_types_data = [
        {"unit": "Секунды", "lower_is_better": True},       # Для коротких дистанций
        {"unit": "Минуты", "lower_is_better": True},        # Для кроссов и марафонов
        {"unit": "Метры", "lower_is_better": False},        # Для прыжков и метаний
        {"unit": "Сантиметры", "lower_is_better": False},   # Для точных замеров гимнастики
        {"unit": "Килограммы", "lower_is_better": False},   # Для тяжелой атлетики
        {"unit": "Количество раз", "lower_is_better": False},# Для подтягиваний, отжиманий
        {"unit": "Баллы", "lower_is_better": False},        # Судейские оценки (фигурное катание и тд)
        {"unit": "Очки", "lower_is_better": False},         # Игровые виды
    ]
    stage_types = {}
    for st_data in stage_types_data:
        st = StageType.objects.create(
            measure_unit=st_data["unit"], 
            is_lower_better=st_data["lower_is_better"]
        )
        stage_types[st_data["unit"]] = st

    # 6. Создаем структуру турнира
    print("🏆 Создаем соревнование и этапы...")
    competition = Competition.objects.create(
        title="Всероссийский летний фестиваль ГТО 2026",
        start_date=date.today(),
        type=comp_types["Готов к труду и обороне (ГТО)"],
        status=Competition.StatusChoices.ACTIVE,
        created_by=org_user,
        chief_judge=chief_user,
        has_individual=True,
        has_team=False
    )

    # Добавляем разнообразные этапы для демонстрации разных метрик
    Stage.objects.create(competition=competition, name="Бег на 100 м", type=stage_types["Секунды"])
    Stage.objects.create(competition=competition, name="Кросс на 3 км", type=stage_types["Минуты"])
    Stage.objects.create(competition=competition, name="Прыжок в длину с места", type=stage_types["Сантиметры"])
    Stage.objects.create(competition=competition, name="Подтягивания на высокой перекладине", type=stage_types["Количество раз"])
    Stage.objects.create(competition=competition, name="Метание спортивного снаряда", type=stage_types["Метры"])

    # 7. Генерируем 25 реалистичных участников
    print("🏃‍♂️ Генерируем участников...")
    first_names = ["Александр", "Дмитрий", "Максим", "Сергей", "Андрей", "Алексей", "Артем", "Илья", "Кирилл", "Михаил", "Никита", "Матвей", "Роман", "Егор", "Арсений", "Денис", "Тимур", "Влад", "Иван", "Павел"]
    last_names = ["Смирнов", "Иванов", "Кузнецов", "Соколов", "Попов", "Лебедев", "Козлов", "Новиков", "Морозов", "Петров", "Волков", "Соловьев", "Васильев", "Зайцев", "Павлов", "Семенов", "Голубев", "Виноградов", "Богданов", "Воробьев"]

    participants_created = 0
    # Обернем в транзакцию для скорости
    with transaction.atomic():
        for i in range(1, 26):
            full_name = f"{random.choice(last_names)} {random.choice(first_names)}"
            bib_number = f"{i:03d}" # Генерирует номера 001, 002... 025
            
            Participant.objects.create(
                competition=competition,
                full_name=full_name,
                bib_number=bib_number
            )
            participants_created += 1

    # 8. Вывод итогов
    print("\n" + "="*55)
    print("🎉 БАЗА ДАННЫХ УСПЕШНО СГЕНЕРИРОВАНА!")
    print("="*55)
    print(f"Турнир: {competition.title}")
    print(f"Категория: {competition.type.type_name}")
    print(f"Спортсменов создано: {participants_created}")
    print(f"Этапов создано: {competition.stages.count()} (с разными метриками)")
    print("\n🔑 ДОСТУПЫ К ТЕСТОВЫМ АККАУНТАМ:")
    print("-" * 55)
    for role, login, pwd in users_info:
        print(f"[{role: <15}] Логин: {login: <12} | Пароль: {pwd}")
    print("="*55 + "\n")

if __name__ == "__main__":
    run_seed()