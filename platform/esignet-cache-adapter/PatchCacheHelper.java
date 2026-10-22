import java.nio.file.*;
import jdk.internal.org.objectweb.asm.*;

/** Build-time patch only: preserve upstream methods verbatim for legacy reads. */
public class PatchCacheHelper {
 public static void main(String[] args)throws Exception {
  byte[] raw=Files.readAllBytes(Paths.get(args[0]));ClassReader reader=new ClassReader(raw);ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS);int[] count={0};
  String helper="io/mosip/esignet/services/AuthorizationHelperService",codec="io/mosip/esignet/nativecache/NativeCacheCodec";
  ClassVisitor visitor=new ClassVisitor(Opcodes.ASM5,writer){
   public MethodVisitor visitMethod(int access,String name,String desc,String signature,String[] exceptions){
    if((name.equals("encryptIndividualId")||name.equals("decryptIndividualId")) && desc.equals("(Ljava/lang/String;)Ljava/lang/String;")){
     if((access&Opcodes.ACC_PRIVATE)==0)throw new IllegalStateException("Unexpected helper visibility");
     count[0]++;return super.visitMethod(access,"kdbtLegacy_"+name,desc,signature,exceptions);
    }
    return super.visitMethod(access,name,desc,signature,exceptions);
   }
   public void visitEnd(){
    for(boolean encrypt:new boolean[]{true,false}){
     String name=encrypt?"encryptIndividualId":"decryptIndividualId",desc="(Ljava/lang/String;)Ljava/lang/String;";
     MethodVisitor m=super.visitMethod(Opcodes.ACC_PRIVATE,name,desc,null,null);m.visitCode();Label legacy=new Label();
     if(encrypt)m.visitMethodInsn(Opcodes.INVOKESTATIC,codec,"nativeWrites","()Z",false);
     else {m.visitVarInsn(Opcodes.ALOAD,1);m.visitMethodInsn(Opcodes.INVOKESTATIC,codec,"isNative","(Ljava/lang/String;)Z",false);}
     m.visitJumpInsn(Opcodes.IFEQ,legacy);m.visitVarInsn(Opcodes.ALOAD,1);m.visitMethodInsn(Opcodes.INVOKESTATIC,codec,encrypt?"encrypt":"decrypt",desc,false);m.visitInsn(Opcodes.ARETURN);
     m.visitLabel(legacy);m.visitFrame(Opcodes.F_SAME,0,null,0,null);m.visitVarInsn(Opcodes.ALOAD,0);m.visitVarInsn(Opcodes.ALOAD,1);m.visitMethodInsn(Opcodes.INVOKESPECIAL,helper,"kdbtLegacy_"+name,desc,false);m.visitInsn(Opcodes.ARETURN);m.visitMaxs(0,0);m.visitEnd();
    }
    super.visitEnd();
   }
  };
  reader.accept(visitor,0);if(count[0]!=2)throw new IllegalStateException("Expected exactly two legacy methods");Files.write(Paths.get(args[1]),writer.toByteArray());
 }
}
