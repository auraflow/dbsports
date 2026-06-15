from django import forms
from .models import Result, Competition, Participant, Stage, Team, TeamMember
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

User = get_user_model()

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
        fields = ['title', 'start_date', 'type', 'status', 'has_individual', 'has_team', 'chief_judge']

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # В выпадающем списке показываем ТОЛЬКО пользователей с ролью Главного судьи
        self.fields['chief_judge'].queryset = User.objects.filter(role__role_name='Главный судья')

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
    # Виртуальные поля для настроек (не идут напрямую в БД)
    multiplier_val = forms.DecimalField(required=False, label="Множитель результата", initial=1.0)
    iaaf_a = forms.FloatField(required=False, label="IAAF Константа A (например, 25.43)")
    iaaf_b = forms.FloatField(required=False, label="IAAF Константа B (например, 18.0)")
    iaaf_c = forms.FloatField(required=False, label="IAAF Константа C (например, 1.81)")

    # НОВОЕ ПОЛЕ ДЛЯ ПЛАВАНИЯ
    fina_base = forms.FloatField(required=False, label="Рекордное время (Base Time в сек)")

    # НОВЫЕ ПОЛЯ СИНКЛЕРА
    sinclair_a = forms.FloatField(required=False, label="Синклер Константа A (например, 0.7519)")
    sinclair_b = forms.FloatField(required=False, label="Синклер Константа B (например, 175.5)")
    
    class Meta:
        model = Stage
        fields = ['name', 'type', 'judges', 'scoring_method']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'judges': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'scoring_method': forms.Select(attrs={'class': 'form-select', 'id': 'id_scoring_method'}),
        }

    def __init__(self, *args, **kwargs):
        # 1. Извлекаем competition из переданных аргументов
        competition = kwargs.pop('competition', None)
        super().__init__(*args, **kwargs)

        # 2. Оставляем только судей в списке (твоя старая логика)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.fields['judges'].queryset = User.objects.filter(role__role_name='Судья')
        self.fields['judges'].required = False

        # 3. Распаковка JSON при РЕДАКТИРОВАНИИ
        if self.instance and self.instance.pk:
            config = self.instance.scoring_config or {}
            method = self.instance.scoring_method
            
            if method == 'multiplier':
                self.initial['multiplier_val'] = config.get('value_multiplier', 1)
            elif method == 'iaaf':
                self.initial['iaaf_a'] = config.get('a', '')
                self.initial['iaaf_b'] = config.get('b', '')
                self.initial['iaaf_c'] = config.get('c', '')
            # ДОБАВИЛИ РАСПАКОВКУ ДЛЯ ПЛАВАНИЯ
            elif method == 'fina':
                self.initial['fina_base'] = config.get('base_time', '')
            elif method == 'sinclair':
                self.initial['sinclair_a'] = config.get('sinclair_a', '')
                self.initial['sinclair_b'] = config.get('sinclair_b', '')

        # 4. Динамическая фильтрация алгоритмов по типу соревнования
        allowed_methods = [
            ('normalization', 'Линейная нормализация (Баллы 0-100)'),
            ('crossfit', 'Очки за места (CrossFit)'),
            ('multiplier', 'Кастомный множитель'),
        ]
        
        if competition and competition.type:
            comp_category = competition.type.type_name.lower()
            if 'атлетика' in comp_category or 'многоборье' in comp_category:
                if 'тяжелая' in comp_category or 'пауэрлифтинг' in comp_category or 'гиревой' in comp_category:
                    allowed_methods.append(('sinclair', 'Коэффициент Синклера (От веса тела)'))
                else:
                    allowed_methods.append(('iaaf', 'Официальная формула IAAF (Многоборье)'))
            elif 'плавание' in comp_category:
                allowed_methods.append(('fina', 'Очки FINA (Мировой стандарт)'))
                
        self.fields['scoring_method'].choices = allowed_methods

        # Стилизуем виртуальные поля
        for field in ['multiplier_val', 'iaaf_a', 'iaaf_b', 'iaaf_c']:
            self.fields[field].widget.attrs.update({'class': 'form-control'})

    def save(self, commit=True):
        stage = super().save(commit=False)
        method = stage.scoring_method
        
        # 5. Упаковка виртуальных полей обратно в JSON
        if method == 'multiplier':
            stage.scoring_config = {
                'value_multiplier': float(self.cleaned_data.get('multiplier_val') or 1)
            }
        elif method == 'iaaf':
            stage.scoring_config = {
                'a': self.cleaned_data.get('iaaf_a') or 0.0,
                'b': self.cleaned_data.get('iaaf_b') or 0.0,
                'c': self.cleaned_data.get('iaaf_c') or 0.0
            }
        # УПАКОВКА ДЛЯ ПЛАВАНИЯ
        elif method == 'fina':
            stage.scoring_config = {
                'base_time': float(self.cleaned_data.get('fina_base') or 0.0)
            }
        elif method == 'sinclair':
            stage.scoring_config = {
                'sinclair_a': float(self.cleaned_data.get('sinclair_a') or 0.0),
                'sinclair_b': float(self.cleaned_data.get('sinclair_b') or 0.0)
            }
        else:
            # Для Normalization и CrossFit доп. настройки пока не нужны
            stage.scoring_config = {}
            
        if commit:
            stage.save()
            self.save_m2m() # Важно для сохранения поля judges (ManyToMany)
        return stage

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