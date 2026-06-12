from django.db.models import F
from .models import Stage, Result

def calculate_stage_standings(stage_id):
    """
    Функция рассчитывает итоговые значения и распределяет места участников этапа 
    на основе правил из главы 2.3.3.
    """
    stage = Stage.objects.select_related('type').get(id=stage_id)

    # 1. ЗАЩИТА: Берем только верифицированные Главным судьей результаты
    qs = Result.objects.filter(
        stage=stage, 
        is_verified=True
    ).select_related('participant')

    # 2. ЛОГИКА СОРТИРОВКИ И ШТРАФОВ
    if stage.type.is_lower_better:
        # Если меньше = лучше (например, бег на 100м)
        # Штраф прибавляется к результату (штрафные секунды)
        # Сортируем по возрастанию (от меньшего времени к большему)
        qs = qs.annotate(
            final_score=F('value') + F('penalty_value')
        ).order_by('final_score')
    else:
        # Если больше = лучше (например, подтягивания, прыжки в длину)
        # Штраф вычитается из результата (штрафные баллы/метры)
        # Сортируем по убыванию (от большего количества к меньшему)
        qs = qs.annotate(
            final_score=F('value') - F('penalty_value')
        ).order_by('-final_score')

    # 3. РАСПРЕДЕЛЕНИЕ МЕСТ
    standings = []
    for index, result in enumerate(qs, start=1):
        standings.append({
            'place': index,
            'participant': result.participant,
            'original_value': result.value,
            'penalty': result.penalty_value,
            'final_score': result.final_score,
            'result_id': result.id # Может пригодиться для ссылок в шаблоне
        })

    return standings