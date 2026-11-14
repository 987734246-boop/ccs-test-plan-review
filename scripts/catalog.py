"""Curated navigation and applicability facts; original wording stays in the local pack."""

TITLES = {
    "1.1":"适用范围", "1.2":"定义", "1.3":"型式认可试验",
    "2.1":"外观检查", "2.2":"性能试验", "2.3":"绝缘电阻测量", "2.4":"能源波动试验",
    "2.5":"能源故障试验", "2.6":"倾斜和摇摆试验", "2.7":"振动试验", "2.8":"高温试验",
    "2.9":"低温试验", "2.10":"交变湿热试验", "2.11":"恒定湿热试验", "2.12":"盐雾试验Kb",
    "2.13":"盐雾试验Ka", "2.14":"耐电压试验", "2.15":"外壳防护试验", "2.16":"滞燃试验",
    "3.1":"电磁兼容性一般要求", "3.2":"传导发射测量", "3.3":"外壳端口辐射发射测量",
    "3.4":"静电放电抗扰度试验", "3.5":"射频电磁场辐射抗扰度试验", "3.6":"电快速瞬变脉冲群抗扰度试验",
    "3.7":"浪涌抗扰度试验", "3.8":"低频传导抗扰度试验", "3.9":"射频场感应的传导骚扰抗扰度试验",
    "4.1":"航行与无线电通信设备一般要求", "4.2":"航行与无线电通信设备试验项目", "A":"引用标准对照"
}
BASIC = list(range(1, 17))
# Rows of table 1.3.3a: 1..17, including the EMC family at row 17.
ENVIRONMENT = {
    "A":[1,2,3,4,5,6,7,11,14,15,16,17],
    "B":[1,2,3,4,5,6,7,8,9,10,14,15,16,17],
    "C":[1,2,3,4,5,6,7,8,9,10,14,15,16,17],
    "D":[1,2,3,4,5,6,7,8,9,10,14,15,16,17],
    "E":[1,2,3,4,5,6,7,8,9,10,12,13,14,15,16,17]
}
# Equipment columns of table 1.3.3b. Distinguish motor and transformer for row 4.
EQUIPMENT = {
    "motor":[1,2,3,4,6,7,10,11,13,14,15,16,17],
    "transformer":[1,2,3,6,7,10,11,13,14,15,16,17],
    "switchgear":[1,2,3,4,6,7,10,11,12,14,15,16,17],
    "electronic":[1,2,3,4,5,6,7,8,9,10,11,12,14,15,16,17]
}
EMC = {
    "induction_motor":[], "synchronous_motor":[2], "dc_motor":[2], "transformer":[],
    "non_electronic_breaker":[8], "relay_control":[7],
    "electronic_controller":list(range(2,10)), "computer":list(range(2,10)), "sensor":list(range(2,10)),
    "converter":list(range(2,10)), "charging_converter":[2,3]
}


def parameters():
    """Explicit checks with mandatory contextual confirmation; not inferred from OCR."""
    records=[]
    def add(clause, pid, label, unit, operator, values, conditions=None):
        records.append({"id":pid,"clause":clause,"label":label,"required_unit":unit,"operator":operator,
                        **values,"conditions":conditions or {},"review_state":"source_checked",
                        "scope_note":"须核对该试验分支、工况及外部标准；不覆盖未列参数"})
    add("2.5","power_cut_count","切断次数","1","equal",{"expected":3},{"extended_startup":False})
    add("2.5","power_cut_duration","每次切断时间","s","equal",{"expected":30})
    add("2.6","static_angle","一般情况静态倾角","deg","equal",{"expected":22.5},{"general_inclination_case":True})
    add("2.6","static_minutes","一般情况每方向静态保持","min","ge",{"min":15},{"general_inclination_case":True})
    add("2.6","rolling_period","摇摆周期","s","equal",{"expected":10},{"general_inclination_case":True})
    add("2.6","rolling_minutes","摇摆持续时间","min","ge",{"min":15},{"general_inclination_case":True})
    add("2.7","vibration_sweep","振动扫频速率","oct/min","le",{"max":1})
    add("2.7","vibration_axes","互相垂直的试验轴数","1","equal",{"expected":3})
    add("2.7","no_resonance_frequency","无明显共振点时频率","Hz","equal",{"expected":30},{"resonance_found":False})
    add("2.7","no_resonance_minutes","无明显共振点时耐振时间","min","equal",{"expected":90},{"resonance_found":False})
    add("2.7","resonance_minutes","每个共振频率耐振时间","min","equal",{"expected":90},{"resonance_found":True,"clustered_resonances":False})
    add("2.7","clustered_minutes","相近共振频率替代扫频时长","min","equal",{"expected":120},{"resonance_found":True,"clustered_resonances":True})
    add("2.8","dry_heat_duration","高温保持时间","h","equal",{"expected":16},{"agreed_special_heat":False})
    add("2.8","dry_heat_55","一般高温条件","C","equal",{"expected":55,"abs_tolerance":2},{"high_heat_environment":False,"agreed_special_heat":False})
    add("2.8","dry_heat_70","高热度环境条件","C","equal",{"expected":70,"abs_tolerance":2},{"high_heat_environment":True,"agreed_special_heat":False})
    add("2.9","cold_duration","低温保持时间","h","equal",{"expected":2})
    add("2.10","damp_cycles_electronic","非电机变压器的交变湿热周期","1","equal",{"expected":2},{"equipment_type":["electronic","switchgear"]})
    add("2.10","damp_cycles_motor","电机变压器的交变湿热周期","1","equal",{"expected":6},{"equipment_type":["motor","transformer"]})
    add("2.11","steady_damp_duration","恒定湿热保持时间","h","equal",{"expected":96})
    add("2.11","steady_damp_temperature","恒定湿热温度","C","equal",{"expected":40,"abs_tolerance":2})
    add("2.11","steady_damp_humidity","恒定湿热相对湿度","%","equal",{"expected":93,"abs_tolerance":3})
    add("2.12","salt_kb_cycles","Kb喷雾周期数","1","equal",{"expected":4})
    add("2.12","salt_kb_spray","Kb每周期连续喷雾时间","h","equal",{"expected":2})
    add("2.14","dielectric_duration","耐电压保持时间","min","equal",{"expected":1})
    add("3.4","esd_contact","接触放电电压","kV","equal",{"expected":6})
    add("3.4","esd_interval","相邻放电最小间隔","s","ge",{"min":1})
    add("3.6","burst_polarity_duration","脉冲群每极性持续时间","min","equal",{"expected":5})
    add("3.7","surge_positive_count","选定点正极性最少脉冲数","1","ge",{"min":5})
    add("3.7","surge_negative_count","选定点负极性最少脉冲数","1","ge",{"min":5})
    return records


def applicability(clause, equipment, tables=None):
    """Conservative table routing; special standards and approvals stay project-specific."""
    env_table=tables.get('environment',ENVIRONMENT) if tables else ENVIRONMENT
    equipment_table=tables.get('equipment',EQUIPMENT) if tables else EQUIPMENT
    emc_table=tables.get('emc',EMC) if tables else EMC
    if equipment.get("navigation_radio") is True:
        return None,"航行/无线电通信设备须按第4章及相应标准分流"
    kind=equipment.get("equipment_type"); env=equipment.get("environment")
    if kind not in equipment_table or env not in env_table:
        return None,"须确认设备类型及安装环境A–E"
    if equipment.get("other_ccs_requirement") is not False:
        return None,"须确认有无其他CCS明文规定或特殊标准"
    chapter,number=map(int,clause.split('.'))
    if chapter==2:
        row=number
        if row not in equipment_table[kind] or row not in env_table[env]:
            # Cold rooms below +5 C need specific evaluation even outside E.
            if row==9 and env!='E' and equipment.get('cold_location') is not False:
                return None,"寒冷处所实际温度条件须另行核对"
            return False,"按环境表、设备表及已确认条件未触发；特殊要求另核"
        if row==6:
            moving=equipment.get('moving_parts'); liquid=equipment.get('free_liquid_surface')
            if moving is False and liquid is False: return False,"表1.3.3a/b注：无运动部件且无自由液面"
            if moving is not True and liquid is not True: return None,"须确认运动部件和自由液面"
        if row==5:
            if equipment.get('control_or_computer') is False: return False,"表1.3.3a/b注：控制等指定用途或计算机条件未触发"
            if equipment.get('control_or_computer') is not True: return None,"能源故障试验须确认控制等指定用途或计算机范围"
        if row==16:
            value=equipment.get('nonmetal_enclosure')
            if value is None: return None,"滞燃范围须确认非金属壳体"
            if value is False: return False,"表1.3.3a/b注：该项非金属壳体条件未触发"
        return True,"环境及设备表共同触发，须同时核对两表脚注与详细条款"
    if chapter==3:
        emc_type=equipment.get('emc_type')
        if emc_type not in emc_table: return None,"须按表3.1.2确认具体EMC设备类型和端口"
        applies=number in emc_table[emc_type]
        if number==8:
            if equipment.get('battery_only') is True: return False,"表3.1.2注：仅由蓄电池供电"
            if equipment.get('battery_only') is None: return None,"须确认是否仅由蓄电池供电"
        if number in (2,3) and not applies:
            if equipment.get('may_cause_em_interference') is True: return True,"1.3.11发射要求仍须考虑"
            if equipment.get('may_cause_em_interference') is not False: return None,"须核对1.3.11的发射要求触发条件"
        return applies,"按表3.1.2、脚注和1.3.11选择；端口覆盖仍需审查"
    return None,"由验船师核对适用性"
