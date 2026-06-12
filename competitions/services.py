from .models import Stage, Result

def calculate_stage_standings(stage_id):
    """
    Функция рассчитывает итоговые значения и распределяет места участников этапа
    на основе правил из главы 2.3.3.
    """
    stage = Stage.objects.select_related('type').get(id=stage_id)
    # Берем все результаты этапа (в идеале только is_verified=True, но пока берем все для теста)
    results = Result.objects.filter(stage=stage).select_related('participant')
    
    standings = []
    
    for res in results:
        penalty = res.penalty_value if res.penalty_value else 0
        
        # Логика из диплома: если замер в секундах, штраф прибавляется. Если в баллах - вычитается.
        if stage.type.measure_unit.lower() in ['секунды', 'сек', 'с', 'время']:
            final_value = float(res.value) + float(penalty)
        else:
            final_value = float(res.value) - float(penalty)
            
        standings.append({
            'participant': res.participant.full_name,
            'bib_number': res.participant.bib_number,
            'original_value': res.value,
            'penalty': penalty,
            'final_value': final_value,
        })
    
    # Сортировка списка. 
    # Если время - сортируем по возрастанию (кто быстрее, тот и первый).
    # Если баллы - сортируем по убыванию (у кого больше, тот и первый).
    is_time_based = stage.type.measure_unit.lower() in ['секунды', 'сек', 'с', 'время']
    standings.sort(key=lambda x: x['final_value'], reverse=not is_time_based)
    
    # Присвоение мест
    for index, item in enumerate(standings):
        item['place'] = index + 1
        
    return standings