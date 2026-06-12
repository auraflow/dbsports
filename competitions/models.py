from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser

# 1. Роли пользователей
class Role(models.Model):
    role_name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.role_name

# 2. Расширенная модель пользователей (вместо стандартной таблицы users)
class User(AbstractUser):
    full_name = models.CharField(max_length=150)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True)

    def __str__(self):
        return self.full_name if self.full_name else self.username

# 3. Типы соревнований
class CompetitionType(models.Model):
    type_name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.type_name

# 4. Соревнования
class Competition(models.Model):
    title = models.CharField(max_length=200, verbose_name='Название соревнования')
    start_date = models.DateField(verbose_name='Дата начала')
    type = models.ForeignKey(CompetitionType, on_delete=models.SET_NULL, null=True, verbose_name='Тип')
    status = models.CharField(max_length=50, default='Активно', verbose_name='Статус')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # НОВЫЕ ПОЛЯ КОНСТРУКТОРА
    has_individual = models.BooleanField(default=True, verbose_name='Проводить личный зачет')
    has_team = models.BooleanField(default=False, verbose_name='Проводить командный зачет')

    is_archived = models.BooleanField(default=False, verbose_name="В архиве")

    def __str__(self):
        return self.title

# 5. Типы замеров для этапов
class StageType(models.Model):
    measure_unit = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.measure_unit

# 6. Этапы соревнований
class Stage(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='stages')
    name = models.CharField(max_length=200)
    type = models.ForeignKey(StageType, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.competition.title} - {self.name}"

# 7. Команды
class Team(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='teams')
    team_name = models.CharField(max_length=150)

    def __str__(self):
        return self.team_name

# 8. Участники соревнований
class Participant(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='participants')
    full_name = models.CharField(max_length=150)
    bib_number = models.CharField(max_length=20, blank=True, null=True, verbose_name='Стартовый номер')

    def __str__(self):
        return f"[{self.bib_number}] {self.full_name}"

# 9. Связь участников и команд (состав команд)
class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='members')
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='teams')

# 10. Результаты этапов
class Result(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='results')
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name='results')
    judge = models.ForeignKey(User, on_delete=models.PROTECT, related_name='recorded_results')
    value = models.DecimalField(max_digits=12, decimal_places=3)
    penalty_value = models.DecimalField(max_digits=12, decimal_places=3, default=0.000, null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.participant.full_name} -> {self.stage.name}: {self.value}"
    
# 11. Журнал изменений результатов (Аудит для Главного судьи)
class ResultLog(models.Model):
    result = models.ForeignKey(Result, on_delete=models.CASCADE, related_name='logs')
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT)
    old_value = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    new_value = models.DecimalField(max_digits=12, decimal_places=3)
    comment = models.TextField()
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Изменение результата #{self.result.id} пользователем {self.changed_by.username}"

class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        verbose_name="Пользователь"
    )
    competition = models.ForeignKey(
        'Competition', 
        on_delete=models.SET_NULL,
        null=True, 
        blank=True, 
        verbose_name="Соревнование"
    )
    action = models.CharField(max_length=255, verbose_name="Действие")
    details = models.TextField(verbose_name="Подробности")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Дата и время")

    class Meta:
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"
        ordering = ['-timestamp']

    def __str__(self):
        date_str = self.timestamp.strftime('%d.%m.%Y %H:%M')
        return f"{date_str} | {self.user} - {self.action}"