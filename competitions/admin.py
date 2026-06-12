from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Role, CompetitionType, Competition, StageType, Stage, Team, Participant, TeamMember, Result

# 1. Регистрируем нашего расширенного пользователя
# Создаем кастомный класс для отображения расширенной модели пользователя
class CustomUserAdmin(UserAdmin):
    # Добавляем новые поля в окно редактирования существующего пользователя
    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация', {'fields': ('full_name', 'role')}),
    )
    # Добавляем новые поля в окно создания нового пользователя
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительная информация', {'fields': ('full_name', 'role')}),
    )
    # Выводим эти поля в общую таблицу пользователей (как на скриншоте)
    list_display = ('username', 'full_name', 'role', 'is_staff')

# Регистрируем модель с новым классом
admin.site.register(User, CustomUserAdmin)

# 2. Простая регистрация базовых справочников
admin.site.register(Role)
admin.site.register(CompetitionType)
admin.site.register(StageType)
admin.site.register(Team)
admin.site.register(TeamMember)

# 3. Регистрация основных таблиц с красивым отображением колонок
@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ('title', 'start_date', 'status', 'type') # Какие колонки показывать в списке
    list_filter = ('status', 'type')                         # Панель фильтрации сбоку

@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ('name', 'competition', 'type')
    list_filter = ('competition',)

@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'bib_number', 'competition')
    search_fields = ('full_name', 'bib_number')              # Строка поиска по ФИО и номеру

@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ('participant', 'stage', 'value', 'is_verified', 'created_at')
    list_filter = ('is_verified', 'stage__competition')