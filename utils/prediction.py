def calculate_class_percentage(prediction):
    """
    Calculate the percentage of each class in the predictions.

    :param prediction: The prediction object returned from Roboflow.
    :return: A dictionary with class names as keys and their corresponding percentage as values.
    """
    total_area = 0
    class_areas = {}

    # Calculate total area and class-specific areas
    for item in prediction['predictions']:
        box_width = item['width']
        box_height = item['height']
        box_area = box_width * box_height
        total_area += box_area

        # Add area to the corresponding class
        class_name = item['class']
        if class_name not in class_areas:
            class_areas[class_name] = 0
        class_areas[class_name] += box_area

    # Calculate the percentage of each class
    class_percentages = {}
    if total_area > 0:
        for class_name, area in class_areas.items():
            class_percentages[class_name] = round((area / total_area) * 100, 2)  # Round to 2 decimal places
    else:
        return {class_name: 0 for class_name in class_areas}

    return class_percentages


def hex_to_bgr(hex_color):
    """Convert hex color to BGR tuple"""
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return (rgb[2], rgb[1], rgb[0])  # Convert RGB to BGR

def colormap(labels):
    classes = {
        "Attrited Enamel": '#00CED1',
        "Bone": '#AFEEEE',
        "Bone level": '#ADD8E6',
        "BoneLoss-InterRadicular": '#800020',
        "Boneloss-Interdental": '#800020',
        "CEJ": '#FFC0CB',
        "Calculus": '#4B0082',
        "Caries": '#008080',
        "ConeCut": '#AFEEEE',
        "Crown Prosthesis": '#C0C0C0',
        "Enamel": '#FFB6C1',
        "Impacted Molar": '#E6E6FA',
        "Implant": '#FFD700',
        "Incisor": '#FFFFE0',
        "InfAlvNrv": '#4169E1',
        "Mandibular Canine": '#90EE90',
        "Mandibular Molar": '#90EE90',
        "Mandibular Premolar": '#E6E6FA',
        "Mandibular Tooth": '#CCFF99',
        "Maxilary Canine": '#ADD8E6',
        "Maxilary Premolar": '#FFDAB9',
        "Maxillary Molar": '#87CEEB',
        "Maxillary Tooth": '#FFC0CB',
        "Missing Tooth": '#4169E1',
        "Obturated Canal": '#FF8C00',
        "Open Margin": '#8B4513',
        "OverHanging Restoration": '#191970',
        "Periapical Pathology": '#DC143C',
        "Pulp": '#FFA07A',
        "Restoration": '#FFBF00',
        "Root Stump": '#FF8C00',
        "Sinus": '#AFEEEE',
        "cr": '#008080',
        "crown length": '#8B4513',
        "im": '#FFD700',
        "nrv": '#FF8C00',
        "10": '#FFA07A',
        "11": '#FFB6C1',
        "12": '#87CEEB',
        "13": '#FFC0CB',
        "14": '#4169E1',
        "15": '#8B4513',
        "16": '#90EE90',
        "17": '#4B0082',
        "18": '#800020',
        "19": '#FF8C00',
        "20": '#DC143C',
        "21": '#00CED1',
        "22": '#AFEEEE',
        "23": '#800020',
        "24": '#FFDAB9',
        "25": '#DB7093',
        "26": '#FFD700',
        "27": '#E6E6FA',
        "28": '#CCFF99',
        "29": '#8622FF',
        "30": '#FE0056',
        "31": '#DC143C',
        "32": '#FF8C00',
        "4": '#CCFF99',
        "5": '#8622FF',
        "6": '#FE0056',
        "7": '#DC143C',
        "8": '#FF8C00',
        "9": '#008080',
        "Impacted Incisors": '#90EE90',
        "Impacted Molar": '#FFC0CB',
        "Inf Alv Nrv": '#87CEEB',
        "License- CC BY 4-0": '#008080',
        "Mandibular Fracture": '#4169E1',
        "Provided by a Roboflow user": '#FFA07A',
        "cone cut": '#4B0082',
        "https-universe-roboflow-com-salud360-dental-qbbud": '#FFB6C1',
        "pathology": '#8B4513',
    }
    
    colors = []
    hex_codes = {}
    for label in labels:
        if label in classes:
            colors.append(classes[label])
            hex_codes[label] = classes[label]
        else:
            # Default color for unknown classes
            colors.append('#FFFFFF')
            hex_codes[label] = '#FFFFFF'
    return colors, hex_codes