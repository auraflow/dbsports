import math
from django.db.models import F
from .models import Stage, Result
from decimal import Decimal

# ==========================================
# ЯДРО РАСЧЕТА БАЛЛОВ (MATH ENGINE)
# ==========================================

class BaseScoringStrategy:
    """Базовый класс для всех алгоритмов расчета"""
    def __init__(self, stage, config):
        self.stage = stage
        self.config = config
        self.is_lower_better = stage.type.is_lower_better

    def calculate(self, queryset):
        raise NotImplementedError("Каждый алгоритм должен реализовать метод calculate")
        
    def _assign_final_places(self, standings):
        """Олимпийская система распределения мест с учетом ничьих (1, 1, 3, 4...)"""
        # Сортируем по баллам (от большего к меньшему)
        standings.sort(key=lambda x: x['points'], reverse=True)
        
        for i, row in enumerate(standings):
            # Если это не первый участник, и его баллы в точности равны предыдущему
            if i > 0 and row['points'] == standings[i-1]['points']:
                row['place'] = standings[i-1]['place'] # Дублируем место
            else:
                row['place'] = i + 1 # Иначе даем место по порядковому номеру
        return standings


class CrossfitScoring(BaseScoringStrategy):
    """Модель 1: Очки за занятые места"""
    def calculate(self, qs):
        if self.is_lower_better:
            qs = qs.annotate(raw_total=F('value') + F('penalty_value')).order_by('raw_total')
        else:
            qs = qs.annotate(raw_total=F('value') - F('penalty_value')).order_by('-raw_total')

        base_points = Decimal(self.config.get('base_points', 100))
        step = Decimal(self.config.get('step', 5))
        standings = []
        
        # Расчет "Сырого" олимпийского места для начисления равных баллов за ничью
        current_place = 1
        last_val = None
        
        for i, result in enumerate(qs):
            raw = result.raw_total
            if last_val is not None and raw == last_val:
                place = current_place
            else:
                place = i + 1
                current_place = place
                
            points = base_points - (Decimal(place - 1) * step)
            if points < 0:
                points = Decimal(0)

            standings.append({
                'participant': result.participant,
                'original_value': result.value,
                'penalty': result.penalty_value,
                'points': points
            })
            last_val = raw
            
        return self._assign_final_places(standings)


class NormalizationScoring(BaseScoringStrategy):
    """Модель 2: Линейная нормализация"""
    def calculate(self, qs):
        results_data = []
        for r in qs:
            fact = r.value + r.penalty_value if self.is_lower_better else r.value - r.penalty_value
            results_data.append({'obj': r, 'fact': fact})

        if not results_data:
            return []
        min_val = min(r['fact'] for r in results_data)
        max_val = max(r['fact'] for r in results_data)

        standings = []
        for data in results_data:
            fact = data['fact']
            if max_val == min_val:
                points = Decimal(100)
            else:
                if self.is_lower_better:
                    points = ((max_val - fact) / (max_val - min_val)) * Decimal(100)
                else:
                    points = ((fact - min_val) / (max_val - min_val)) * Decimal(100)

            standings.append({
                'participant': data['obj'].participant,
                'original_value': data['obj'].value,
                'penalty': data['obj'].penalty_value,
                'points': round(points, 2)
            })
        return self._assign_final_places(standings)


class MultiplierScoring(BaseScoringStrategy):
    """Модель 3: Кастомный множитель"""
    def calculate(self, qs):
        val_mult = Decimal(self.config.get('value_multiplier', 1))
        pen_mult = Decimal(self.config.get('penalty_multiplier', 1))
        standings = []
        
        for result in qs:
            if self.is_lower_better:
                points = (result.value * -val_mult) - (result.penalty_value * pen_mult)
            else:
                points = (result.value * val_mult) - (result.penalty_value * pen_mult)

            # --- ЗАЩИТА ОТ "ЧЕРНОЙ ДЫРЫ" ---
            # Если баллы ушли в минус, приравниваем их к нулю
            if points < 0:
                points = Decimal(0)
            # -------------------------------
            
            standings.append({
                'participant': result.participant,
                'original_value': result.value,
                'penalty': result.penalty_value,
                'points': round(points, 2)
            })
        return self._assign_final_places(standings)


class IAAFScoring(BaseScoringStrategy):
    """Модель 4: Официальная формула IAAF (Многоборье)"""
    def calculate(self, qs):
        a = float(self.config.get('a', 0))
        b = float(self.config.get('b', 0))
        c = float(self.config.get('c', 0))
        standings = []
        
        for result in qs:
            fact_val = float(result.value + result.penalty_value) if self.is_lower_better else float(result.value - result.penalty_value)
            points = 0
            if a > 0 and b > 0 and c > 0:
                try:
                    if self.is_lower_better and fact_val < b:
                        points = math.floor(a * math.pow((b - fact_val), c))
                    elif not self.is_lower_better and fact_val > b:
                        points = math.floor(a * math.pow((fact_val - b), c))
                except (ValueError, OverflowError):
                    points = 0
            
            standings.append({
                'participant': result.participant,
                'original_value': result.value,
                'penalty': result.penalty_value,
                'points': Decimal(points)
            })
        return self._assign_final_places(standings)


class FINAScoring(BaseScoringStrategy):
    """Модель 5: Очки FINA (Плавание)"""
    def calculate(self, qs):
        base_time = float(self.config.get('base_time', 0))
        standings = []
        
        for result in qs:
            # Штрафы в плавании обычно добавляются секундами
            fact_time = float(result.value + result.penalty_value)
            points = 0
            # Формула FINA: 1000 * (Base Time / Result Time)^3
            if base_time > 0 and fact_time > 0:
                points = math.floor(1000 * math.pow((base_time / fact_time), 3))
            
            standings.append({
                'participant': result.participant,
                'original_value': result.value,
                'penalty': result.penalty_value,
                'points': Decimal(points)
            })
        return self._assign_final_places(standings)

class SinclairScoring(BaseScoringStrategy):
    """Модель 6: Коэффициент Синклера (Тяжелая атлетика / Пауэрлифтинг)"""
    def calculate(self, qs):
        # Официальные коэффициенты Синклера A и B обновляются раз в 4 года (Организатор вводит их)
        a = float(self.config.get('sinclair_a', 0))
        b = float(self.config.get('sinclair_b', 0))
        
        standings = []
        for result in qs:
            body_weight = float(result.participant.weight_kg or 0)
            lifted_weight = float(result.value - result.penalty_value)
            
            points = 0
            if body_weight > 0 and lifted_weight > 0 and a > 0 and b > 0:
                if body_weight <= b:
                    # Формула Синклера: 10 ^ ( A * (log10(body_weight / B))^2 )
                    x = math.log10(body_weight / b)
                    coeff = math.pow(10, (a * (x ** 2)))
                else:
                    # Если штангист весит больше базового супертяжа (B), его коэффициент равен 1.0
                    coeff = 1.0
                
                points = lifted_weight * coeff
            
            standings.append({
                'participant': result.participant,
                'original_value': result.value,
                'penalty': result.penalty_value,
                'points': round(Decimal(points), 2)
            })
            
        return self._assign_final_places(standings)

class ScoringFactory:
    """Фабрика: выбирает нужный калькулятор"""
    @staticmethod
    def get_strategy(stage):
        method = stage.scoring_method
        config = stage.scoring_config or {}

        if method == 'crossfit':
            return CrossfitScoring(stage, config)
        elif method == 'normalization':
            return NormalizationScoring(stage, config)
        elif method == 'multiplier':
            return MultiplierScoring(stage, config)
        elif method == 'iaaf':
            return IAAFScoring(stage, config)
        elif method == 'fina':
            return FINAScoring(stage, config) # ПОДКЛЮЧИЛИ ПЛАВАНИЕ!
        elif method == 'sinclair':
            return SinclairScoring(stage, config)
        else:
            return NormalizationScoring(stage, config)


def calculate_stage_standings(stage_id):
    stage = Stage.objects.select_related('type').get(id=stage_id)
    qs = Result.objects.filter(stage=stage, is_verified=True).select_related('participant')
    strategy = ScoringFactory.get_strategy(stage)
    return strategy.calculate(qs)