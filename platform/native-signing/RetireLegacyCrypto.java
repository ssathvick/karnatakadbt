import java.nio.file.*;
import jdk.internal.org.objectweb.asm.*;
/** Remove legacy cache-key operations after the fenced ciphertext migration. */
public class RetireLegacyCrypto {
 public static void main(String[] args)throws Exception{
  ClassReader reader=new ClassReader(Files.readAllBytes(Paths.get(args[0])));ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS);int[] changed={0};boolean controller=args.length>2&&args[2].equals("jwks");
  ClassVisitor visitor=new ClassVisitor(Opcodes.ASM5,writer){
   public MethodVisitor visitMethod(int access,String name,String desc,String signature,String[] exceptions){
    if(controller)return new MethodVisitor(Opcodes.ASM5,super.visitMethod(access,name,desc,signature,exceptions)){
     public void visitInsn(int opcode){if(name.equals("getAllJwks")&&opcode==Opcodes.ARETURN){super.visitMethodInsn(Opcodes.INVOKESTATIC,"org/karnatakadbt/crypto/NativePublicTrust","merge","(Ljava/util/Map;)Ljava/util/Map;",false);changed[0]++;}super.visitInsn(opcode);}
    };
    if(name.equals("encryptIndividualId")&&desc.equals("(Ljava/lang/String;)Ljava/lang/String;")){
     MethodVisitor m=super.visitMethod(access,name,desc,signature,exceptions);m.visitCode();m.visitVarInsn(Opcodes.ALOAD,1);m.visitMethodInsn(Opcodes.INVOKESTATIC,"io/mosip/esignet/nativecache/NativeCacheCodec","encrypt",desc,false);m.visitInsn(Opcodes.ARETURN);m.visitMaxs(0,0);m.visitEnd();changed[0]++;return null;
    }
    if(name.equals("decryptIndividualId")&&desc.equals("(Ljava/lang/String;)Ljava/lang/String;")){
     MethodVisitor m=super.visitMethod(access,name,desc,signature,exceptions);m.visitCode();m.visitVarInsn(Opcodes.ALOAD,1);m.visitMethodInsn(Opcodes.INVOKESTATIC,"io/mosip/esignet/nativecache/NativeCacheCodec","decrypt",desc,false);m.visitInsn(Opcodes.ARETURN);m.visitMaxs(0,0);m.visitEnd();changed[0]++;return null;
    }
    if(name.startsWith("kdbtLegacy_")||name.equals("getSecretKeyFromHSM")||name.equals("getKeyAlias"))return null;
    return super.visitMethod(access,name,desc,signature,exceptions);
   }
  };reader.accept(visitor,0);if(changed[0]!=(controller?1:2))throw new IllegalStateException("Unexpected crypto patch contract");Files.write(Paths.get(args[1]),writer.toByteArray());
 }
}
