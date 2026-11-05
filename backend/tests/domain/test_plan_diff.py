from backend.domain.plan_diff import plan_differences


def test_diff_includes_domain_settings_additions_removals_and_context():
    base={'workout_plan':{'weekly_training_days':3,'days':[{'day':'周一','exercises':[{'name':'卧推','sets':3}]}]},
          'diet_plan':{'meals':['饭','奶']}}
    new={'workout_plan':{'weekly_training_days':4,'days':[{'day':'周一','exercises':[{'name':'卧推','sets':4}]},{'day':'周五'}]},
         'diet_plan':{'meals':['饭']}}
    changes=plan_differences(base,new,{'training','diet'})
    by_path={item['path']:item for item in changes}
    assert by_path['workout_plan.weekly_training_days']['new_value']==4
    assert by_path['workout_plan.days.0.exercises.0.sets']['context']==['周一','卧推']
    assert by_path['workout_plan.days.1']['change_kind']=='added'
    assert by_path['diet_plan.meals.1']['change_kind']=='removed'


def test_diff_never_discloses_unread_domain_and_distinguishes_null_from_missing():
    changes=plan_differences({'workout_plan':{},'diet_plan':{'secret':'before'}},
        {'workout_plan':{'note':None},'diet_plan':{'secret':'after'}},{'training'})
    assert len(changes)==1
    assert changes[0]['change_kind']=='added' and changes[0]['new_value'] is None
