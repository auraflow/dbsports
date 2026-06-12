from django import forms
from .models import Result, Competition, Participant, Stage, Team, TeamMember

class ResultForm(forms.ModelForm):
    class Meta:
        model = Result
        fields = ['participant', 'value', 'penalty_value', 'comment']
        widgets = {
            'participant': forms.Select(attrs={'class': 'form-select'}),
            'value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}),
            'penalty_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Особые отметки судьи...'}),
        }

# --- НОВЫЕ ФОРМЫ ДЛЯ ОРГАНИЗАТОРА ---

class CompetitionForm(forms.ModelForm):
    class Meta:
        model = Competition
        # Добавили новые поля в список
        fields = ['title', 'start_date', 'type', 'status', 'has_individual', 'has_team']

        # Переопределяем названия полей для интерфейса
        labels = {
            'type': 'Категория / Дисциплина *',
        }

        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: Спартакиада 2-й смены'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Активно / Завершено'}),
            # Делаем красивые свитчи-переключатели
            'has_individual': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_team': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class ParticipantForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ['full_name', 'bib_number']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ФИО спортсмена'}),
            'bib_number': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Стартовый номер'}),
        }

class StageForm(forms.ModelForm):
    class Meta:
        model = Stage
        fields = ['name', 'type']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: Полоса препятствий, Подтягивания'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
        }

class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['team_name']
        widgets = {
            'team_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: 1-й Отряд, Спартанцы'}),
        }

class TeamMemberForm(forms.ModelForm):
    class Meta:
        model = TeamMember
        fields = ['participant']
        widgets = {
            'participant': forms.Select(attrs={'class': 'form-select'}),
        }