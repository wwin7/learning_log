from django import forms

from .models import DailyCheckIn, Entry, Topic

class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ["text", "tags", "category_color"]
        labels = {
            "text": "分类名称",
            "tags": "标签（输入后回车，或用逗号/空格分隔）",
            "category_color": "分类颜色",
        }
        widgets = {
            "text": forms.TextInput(attrs={"class": "form-control", "placeholder": "如：Python / 英语 / 算法"}),
            "tags": forms.TextInput(attrs={"class": "form-control", "placeholder": "输入标签后按回车..."}),
            "category_color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
        }

class EntryForm(forms.ModelForm):
    class Meta:
        model = Entry
        fields = ["text", "tags"]
        labels = {
            "text": "笔记内容",
            "tags": "标签（输入后回车，或用逗号/空格分隔）",
        }
        widgets = {
            "text": forms.Textarea(attrs={"class": "form-control", "rows": 8, "placeholder": "记录今天学到了什么..."}),
            "tags": forms.TextInput(attrs={"class": "form-control", "placeholder": "输入标签后按回车..."}),
        }


class DailyCheckInForm(forms.ModelForm):
    class Meta:
        model = DailyCheckIn
        fields = ["note"]
        labels = {"note": "打卡备注"}
        widgets = {
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "今天最值得记录的一件事"}),
        }
