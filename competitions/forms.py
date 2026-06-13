from django import forms
from .models import Result, Competition, Participant, Stage, Team, TeamMember
from django.core.exceptions import ValidationError

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

# ЗАЩИТА: Проверка основного результата
    def clean_value(self):
        value = self.cleaned_data.get('value')
        if value is not None and value < 0:
            raise ValidationError("Результат не может быть отрицательным.")
        return value

    # ЗАЩИТА: Проверка значения штрафа и защита от NULL
    def clean_penalty_value(self):
        penalty = self.cleaned_data.get('penalty_value')
        
        # Если судья просто оставил поле пустым (ничего не вписал), ставим 0
        if penalty is None:
            return 0.000
            
        if penalty < 0:
            raise ValidationError("Значение штрафа не может быть отрицательным.")
        return penalty

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
            'status': forms.Select(attrs={'class': 'form-select'}),
            # Делаем красивые свитчи-переключатели
            'has_individual': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_team': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    # ЗАЩИТА: Комплексная проверка логики соревнования
    def clean(self):
        cleaned_data = super().clean()
        has_individual = cleaned_data.get('has_individual')
        has_team = cleaned_data.get('has_team')

        # Соревнование должно иметь хотя бы один тип зачета
        if not has_individual and not has_team:
            raise ValidationError("Критическая ошибка: Необходимо выбрать хотя бы один формат проведения (Личный или Командный зачет).")
        
        return cleaned_data

class ParticipantForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ['full_name', 'bib_number']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ФИО спортсмена'}),
            'bib_number': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Стартовый номер'}),
        }

    # ЗАЩИТА: Очистка стартового номера и защита от ошибки IntegrityError
    def clean_bib_number(self):
        bib = self.cleaned_data.get('bib_number')
        # Если номер не ввели (пустая строка), возвращаем строго None (NULL для БД)
        if not bib or str(bib).strip() == "":
            return None
            
        return str(bib).strip()

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